"""Typer-based CLI entry points."""

from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ssh_socks_cli import (
    __version__,
    config,
    firefox,
    health,
    paths,
    route,
    service,
    tunnel,
    watchdog,
)
from ssh_socks_cli.config import AppConfig, ConfigError, FirefoxConfig, TunnelConfig

app = typer.Typer(
    name="ssh-socks",
    help="Manage an SSH-based SOCKS5 tunnel so Firefox routes traffic through your own server.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(name="config", help="View and manage configuration.", no_args_is_help=True)
firefox_app = typer.Typer(name="firefox", help="Firefox SOCKS5 integration.", no_args_is_help=True)
service_app = typer.Typer(name="service", help="Auto-start service management.", no_args_is_help=True)
app.add_typer(config_app)
app.add_typer(firefox_app)
app.add_typer(service_app)

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
    vpn_bypass_default = route.is_public_ip(host)
    vpn_bypass = Confirm.ask(
        "Add direct host route to the SSH server? (recommended when the host is a public IP)",
        default=vpn_bypass_default,
    )

    cfg = AppConfig(
        tunnel=TunnelConfig(
            host=host,
            user=user,
            port=port,
            identity_file=identity,
            local_port=local_port,
            vpn_bypass=vpn_bypass,
        ),
        firefox=FirefoxConfig(),
    )
    paths.ensure_dirs()
    written = config.save(cfg)
    console.print(f"\n[green]✓[/green] Config written to [bold]{written}[/bold]")
    if vpn_bypass and not paths.SUDOERS_FILE.exists():
        console.print(
            "\n[yellow]Tip:[/yellow] Run [cyan]ssh-socks setup[/cyan] to enable "
            "passwordless route management (recommended for vpn_bypass)."
        )
    console.print(
        "Next: [cyan]ssh-socks doctor[/cyan] to verify, then [cyan]ssh-socks start[/cyan]"
    )


# -------------------------------------------------------------------------- start / stop / status


@app.command()
def start() -> None:
    """Start the SOCKS5 tunnel in the background."""
    cfg = _load_or_exit()
    try:
        result = tunnel.start(cfg)
    except tunnel.TunnelError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(
        f"[green]✓[/green] Tunnel started (PID [bold]{result.pid}[/bold]) on "
        f"[cyan]{cfg.tunnel.bind_address}:{cfg.tunnel.local_port}[/cyan]"
    )
    if result.route:
        if result.route.success:
            console.print(
                f"[green]✓[/green] Direct host route added for "
                f"[cyan]{cfg.tunnel.host}[/cyan] via [cyan]{result.route.gateway}[/cyan]"
            )
        else:
            err_console.print(f"[yellow]⚠[/yellow] {result.route.detail}")
    if result.watchdog_pid:
        console.print(
            f"[green]✓[/green] Gateway watchdog started "
            f"(PID [bold]{result.watchdog_pid}[/bold], interval 10s)"
        )


@app.command()
def stop() -> None:
    """Stop the running SOCKS5 tunnel."""
    try:
        cfg = config.load()
        vpn_bypass = cfg.tunnel.vpn_bypass
    except config.ConfigError:
        vpn_bypass = False
    result = tunnel.stop(vpn_bypass=vpn_bypass)
    if result.stopped:
        console.print("[green]✓[/green] Tunnel stopped.")
        if result.route and result.route.success:
            console.print(
                "[green]✓[/green] Direct host route removed"
            )
    else:
        console.print("[yellow]No running tunnel.[/yellow]")


@app.command()
def restart() -> None:
    """Stop and start the tunnel."""
    cfg = _load_or_exit()
    tunnel.stop(vpn_bypass=cfg.tunnel.vpn_bypass)
    try:
        result = tunnel.start(cfg)
    except tunnel.TunnelError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Tunnel restarted (PID [bold]{result.pid}[/bold])")


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
        wd_pid = watchdog.read_pid()
        if wd_pid and watchdog.is_running():
            console.print(
                f"[green]●[/green] watchdog PID [bold]{wd_pid}[/bold]"
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
        ("vpn_bypass", t.vpn_bypass),
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


# -------------------------------------------------------------------------- service subcommands


@service_app.command("install")
def service_install() -> None:
    """Install the auto-start service so the tunnel starts on login."""
    try:
        path = service.install()
    except service.ServiceError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Service installed: [bold]{path}[/bold]")
    console.print("The tunnel will start automatically on next login.")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Remove the auto-start service."""
    try:
        path = service.uninstall()
    except service.ServiceError as e:
        err_console.print(str(e))
        raise typer.Exit(code=1) from e
    console.print(f"[green]✓[/green] Service removed: [bold]{path}[/bold]")


@service_app.command("status")
def service_status() -> None:
    """Show whether the auto-start service is installed."""
    st = service.status()
    if st.installed:
        console.print(
            f"[green]●[/green] installed  platform [bold]{st.platform}[/bold]  "
            f"status [cyan]{st.detail}[/cyan]"
        )
        if st.service_path:
            console.print(f"  path: {st.service_path}")
    else:
        console.print(f"[red]○[/red] not installed  platform [bold]{st.platform}[/bold]")


# -------------------------------------------------------------------------- setup / unsetup


@app.command()
def setup() -> None:
    """Create a sudoers rule for passwordless route management (one-time, requires sudo)."""
    if sys.platform == "win32":
        err_console.print("Setup is not needed on Windows.")
        raise typer.Exit(code=1)

    username = getpass.getuser()
    sudoers_file = paths.SUDOERS_FILE

    if sys.platform == "darwin":
        binary = paths.ROUTE_BINARY_MACOS
    else:
        binary = paths.route_binary_linux()

    rule = f"{username} ALL=(ALL) NOPASSWD: {binary}\n"

    if sudoers_file.exists():
        existing = sudoers_file.read_text()
        if rule.strip() in existing:
            console.print(f"[green]✓[/green] Sudoers rule already exists at {sudoers_file}")
            return

    console.print(f"This will create [bold]{sudoers_file}[/bold] with:")
    console.print(f"  [cyan]{rule.strip()}[/cyan]")
    console.print()

    try:
        # Write the rule via sudo tee
        proc = subprocess.run(
            ["sudo", "tee", str(sudoers_file)],
            input=rule,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            err_console.print(f"Failed to write sudoers file: {proc.stderr.strip()}")
            raise typer.Exit(code=1)

        # Set permissions
        subprocess.run(
            ["sudo", "chmod", "0440", str(sudoers_file)],
            check=True,
            capture_output=True,
            timeout=10,
        )

        # Validate with visudo
        result = subprocess.run(
            ["sudo", "visudo", "-cf", str(sudoers_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # Invalid syntax — remove and error
            subprocess.run(
                ["sudo", "rm", str(sudoers_file)],
                capture_output=True,
                timeout=10,
            )
            err_console.print(f"Sudoers validation failed: {result.stderr.strip()}")
            err_console.print("File removed. Please report this as a bug.")
            raise typer.Exit(code=1)

    except subprocess.TimeoutExpired as e:
        err_console.print("sudo timed out — try running manually.")
        raise typer.Exit(code=1) from e
    except subprocess.CalledProcessError as e:
        err_console.print(f"Failed: {e}")
        raise typer.Exit(code=1) from e

    console.print(f"[green]✓[/green] Sudoers rule created at [bold]{sudoers_file}[/bold]")
    console.print(
        f"Passwordless [cyan]sudo {binary}[/cyan] is now enabled for [bold]{username}[/bold]."
    )


@app.command()
def unsetup() -> None:
    """Remove the sudoers rule for passwordless route management."""
    sudoers_file = paths.SUDOERS_FILE

    if not sudoers_file.exists():
        console.print("[yellow]No sudoers rule found — nothing to remove.[/yellow]")
        return

    try:
        subprocess.run(
            ["sudo", "rm", str(sudoers_file)],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        err_console.print(f"Failed to remove {sudoers_file}: {e}")
        raise typer.Exit(code=1) from e

    console.print(f"[green]✓[/green] Sudoers rule removed: [bold]{sudoers_file}[/bold]")
