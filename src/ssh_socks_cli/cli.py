"""Typer-based CLI entry points."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ssh_socks_cli import __version__, config, firefox, health, paths, tunnel
from ssh_socks_cli.config import AppConfig, ConfigError, FirefoxConfig, TunnelConfig

app = typer.Typer(
    name="ssh-socks",
    help="Manage an SSH-based SOCKS5 tunnel so your browser can bypass corporate VPNs.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(name="config", help="View and manage configuration.", no_args_is_help=True)
firefox_app = typer.Typer(name="firefox", help="Firefox SOCKS5 integration.", no_args_is_help=True)
app.add_typer(config_app)
app.add_typer(firefox_app)

console = Console()
err_console = Console(stderr=True, style="red")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ssh-socks-cli {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


def _load_or_exit() -> AppConfig:
    try:
        return config.load()
    except ConfigError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e


# -------------------------------------------------------------------------- init


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config."),
) -> None:
    """Interactively create the configuration file."""
    cfg_path = paths.config_file()
    if cfg_path.exists() and not force:
        err_console.print(f"Config already exists at {cfg_path}. Use --force to overwrite.")
        raise typer.Exit(code=1)

    console.print("[bold]ssh-socks-cli setup[/bold]")
    console.print("Enter your SSH server details. Press Ctrl-C to abort.\n")

    host = Prompt.ask("SSH host (e.g. proxy.example.com)")
    user = Prompt.ask("SSH user", default="root")
    port = IntPrompt.ask("SSH port", default=22)
    identity_default = str(Path.home() / ".ssh" / "id_ed25519")
    identity = Prompt.ask("Identity file (private key)", default=identity_default)
    local_port = IntPrompt.ask("Local SOCKS5 port", default=1080)

    cfg = AppConfig(
        tunnel=TunnelConfig(
            host=host,
            user=user,
            port=port,
            identity_file=identity,
            local_port=local_port,
        ),
        firefox=FirefoxConfig(),
    )
    paths.ensure_dirs()
    written = config.save(cfg)
    console.print(f"\n[green]✓[/green] Config written to [bold]{written}[/bold]")
    console.print(
        "Next: [cyan]ssh-socks doctor[/cyan] to verify, then [cyan]ssh-socks start[/cyan]"
    )


# -------------------------------------------------------------------------- start / stop / status


@app.command()
def start() -> None:
    """Start the SOCKS5 tunnel in the background."""
    cfg = _load_or_exit()
    try:
        pid = tunnel.start(cfg)
    except tunnel.TunnelError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(
        f"[green]✓[/green] Tunnel started (PID [bold]{pid}[/bold]) on "
        f"[cyan]{cfg.tunnel.bind_address}:{cfg.tunnel.local_port}[/cyan]"
    )


@app.command()
def stop() -> None:
    """Stop the running SOCKS5 tunnel."""
    stopped = tunnel.stop()
    if stopped:
        console.print("[green]✓[/green] Tunnel stopped.")
    else:
        console.print("[yellow]No running tunnel.[/yellow]")


@app.command()
def restart() -> None:
    """Stop and start the tunnel."""
    tunnel.stop()
    cfg = _load_or_exit()
    try:
        pid = tunnel.start(cfg)
    except tunnel.TunnelError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Tunnel restarted (PID [bold]{pid}[/bold])")


@app.command()
def status() -> None:
    """Show tunnel status."""
    st = tunnel.status()
    if st.running:
        try:
            cfg = config.load()
            endpoint = f"{cfg.tunnel.bind_address}:{cfg.tunnel.local_port}"
        except ConfigError:
            endpoint = "(config missing)"
        console.print(
            f"[green]●[/green] running  PID [bold]{st.pid}[/bold]  endpoint [cyan]{endpoint}[/cyan]"
        )
    else:
        console.print("[red]○[/red] not running")


# -------------------------------------------------------------------------- logs


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Tail the log."),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show."),
) -> None:
    """Show the tunnel log."""
    path = tunnel.log_path()
    if not path.exists():
        console.print("[yellow]No log file yet.[/yellow]")
        return
    if follow:
        import subprocess

        tail_bin = "tail"
        if sys.platform == "win32":
            err_console.print("--follow is not supported on Windows. Use a file viewer.")
            raise typer.Exit(code=1)
        subprocess.run([tail_bin, "-n", str(lines), "-f", str(path)])
        return
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in content[-lines:]:
        console.print(line, highlight=False)


# -------------------------------------------------------------------------- doctor


@app.command()
def doctor() -> None:
    """Run environment diagnostics."""
    try:
        cfg: AppConfig | None = config.load()
    except ConfigError:
        cfg = None

    console.print("[bold]ssh-socks-cli doctor[/bold]\n")
    all_ok = True
    for check in health.run_all(cfg):
        if not check.ok:
            all_ok = False
        console.print(str(check))
    console.print()
    if all_ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed — see above.[/red]")
        raise typer.Exit(code=1)


# -------------------------------------------------------------------------- config subcommands


@config_app.command("show")
def config_show() -> None:
    """Print the current configuration."""
    cfg = _load_or_exit()
    table = Table(title="Tunnel")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    t = cfg.tunnel
    for k, v in [
        ("host", t.host),
        ("user", t.user),
        ("port", t.port),
        ("identity_file", t.identity_file or "(default)"),
        ("local_port", t.local_port),
        ("bind_address", t.bind_address),
        ("use_autossh", t.use_autossh if t.use_autossh is not None else "auto"),
        ("compression", t.compression),
        ("server_alive_interval", t.server_alive_interval),
    ]:
        table.add_row(k, str(v))
    console.print(table)


@config_app.command("path")
def config_path() -> None:
    """Print the config file path."""
    console.print(str(paths.config_file()))


# -------------------------------------------------------------------------- firefox subcommands


@firefox_app.command("show")
def firefox_show() -> None:
    """Print the user.js block to stdout."""
    cfg = _load_or_exit()
    console.print(firefox.build_user_js_block(cfg), highlight=False)


@firefox_app.command("apply")
def firefox_apply(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Inject the SOCKS5 block into the default Firefox profile's user.js."""
    cfg = _load_or_exit()
    try:
        profile = firefox.default_profile()
    except firefox.FirefoxError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e

    console.print(f"Default profile: [cyan]{profile.name}[/cyan] ({profile.path})")
    if not yes and not Confirm.ask(
        "Apply ssh-socks-cli SOCKS5 settings to this profile?", default=True
    ):
        raise typer.Exit(code=1)

    written = firefox.apply(cfg, profile)
    console.print(f"[green]✓[/green] Wrote {written}")
    console.print("[yellow]Restart Firefox for changes to take effect.[/yellow]")


@firefox_app.command("reset")
def firefox_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Write a defaults-restoring block so Firefox clears the SOCKS5 settings on restart.

    This is a two-step rollback: reset first, restart Firefox so it overwrites prefs.js
    with Firefox defaults, then optionally `ssh-socks firefox purge` to remove the block
    entirely.
    """
    try:
        profile = firefox.default_profile()
    except firefox.FirefoxError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e

    console.print(f"Default profile: [cyan]{profile.name}[/cyan] ({profile.path})")
    if not yes and not Confirm.ask(
        "Replace the ssh-socks-cli block with a defaults-restoring block?", default=True
    ):
        raise typer.Exit(code=1)
    try:
        written = firefox.reset(profile)
    except firefox.FirefoxError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Wrote defaults block to {written}")
    console.print(
        "[yellow]Restart Firefox for the defaults to take effect.[/yellow] "
        "Then run [cyan]ssh-socks firefox purge[/cyan] to remove the block completely."
    )


@firefox_app.command("purge")
def firefox_purge(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove any ssh-socks-cli block (apply or reset) from user.js entirely.

    Only safe after you've restarted Firefox at least once with a `reset` block in place.
    Otherwise previously-applied prefs will still live in prefs.js.
    """
    try:
        profile = firefox.default_profile()
    except firefox.FirefoxError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e

    console.print(f"Default profile: [cyan]{profile.name}[/cyan] ({profile.path})")
    if not yes and not Confirm.ask(
        "Completely remove ssh-socks-cli block from user.js?", default=True
    ):
        raise typer.Exit(code=1)
    try:
        written = firefox.purge(profile)
    except firefox.FirefoxError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Purged {written}")


@firefox_app.command("profiles")
def firefox_profiles() -> None:
    """List detected Firefox profiles."""
    profiles = firefox.list_profiles()
    if not profiles:
        console.print("[yellow]No Firefox profiles found.[/yellow]")
        return
    table = Table(title="Firefox profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Default")
    table.add_column("Path")
    for p in profiles:
        table.add_row(p.name, "✓" if p.is_default else "", str(p.path))
    console.print(table)
