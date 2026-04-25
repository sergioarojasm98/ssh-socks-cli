"""Environment diagnostics for the `doctor` command."""

from __future__ import annotations

import shutil
import socket
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from ssh_socks_cli.config import AppConfig
from ssh_socks_cli.paths import SUDOERS_FILE
from ssh_socks_cli.route import has_bypass_route, is_public_ip
from ssh_socks_cli.watchdog import is_running as watchdog_is_running


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        status = "[green]✓[/green]" if self.ok else "[red]✗[/red]"
        return f"{status} {self.name}: {self.detail}"


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def check_ssh() -> Check:
    path = _which("ssh")
    if not path:
        return Check("ssh", False, "not found in PATH — install OpenSSH client")
    return Check("ssh", True, path)


def check_autossh() -> Check:
    path = _which("autossh")
    if not path:
        return Check(
            "autossh",
            False,
            "not found (optional — install for auto-reconnect: brew/apt install autossh)",
        )
    return Check("autossh", True, path)


def check_identity_file(identity: Path | None) -> Check:
    if identity is None:
        return Check("identity file", True, "(none configured — using ssh defaults)")
    if not identity.exists():
        return Check("identity file", False, f"not found: {identity}")
    if sys.platform != "win32":
        mode = identity.stat().st_mode & 0o777
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            return Check(
                "identity file",
                False,
                f"permissions too open ({oct(mode)}) — run: chmod 600 {identity}",
            )
    return Check("identity file", True, str(identity))


def check_host_reachable(host: str, port: int, timeout: float = 5.0) -> Check:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return Check("host reachable", True, f"{host}:{port} (TCP connect OK)")
    except OSError as e:
        return Check("host reachable", False, f"{host}:{port} — {e}")


def check_local_port_free(bind: str, port: int) -> Check:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((bind, port))
            return Check("local port", True, f"{bind}:{port} is free")
    except OSError as e:
        return Check(
            "local port",
            False,
            f"{bind}:{port} not bindable — {e} (tunnel may already be running)",
        )


def check_host_route(host: str) -> Check:
    """Check whether the direct host route is active when vpn_bypass is enabled."""
    if not is_public_ip(host):
        return Check("host route", True, f"{host} is private — route not needed")
    if has_bypass_route(host):
        return Check("host route", True, f"route for {host} is active")
    return Check(
        "host route",
        True,
        f"no direct route for {host} (will be added automatically on `ssh-socks start`)",
    )


def run_all(cfg: AppConfig | None) -> list[Check]:
    """Run every diagnostic check. Config is optional (for a pre-init doctor)."""
    checks: list[Check] = [check_ssh(), check_autossh()]
    if cfg is None:
        checks.append(Check("config", False, "no config yet — run `ssh-socks init`"))
    else:
        checks.append(Check("config", True, "loaded"))
        checks.append(check_identity_file(cfg.tunnel.identity_path()))
        checks.append(check_host_reachable(cfg.tunnel.host, cfg.tunnel.port))
        checks.append(check_local_port_free(cfg.tunnel.bind_address, cfg.tunnel.local_port))
    if cfg is not None and cfg.tunnel.vpn_bypass:
        checks.append(check_host_route(cfg.tunnel.host))
        if sys.platform != "win32":
            if SUDOERS_FILE.exists():
                checks.append(Check("sudoers", True, f"{SUDOERS_FILE} exists"))
            else:
                checks.append(
                    Check(
                        "sudoers",
                        False,
                        "no passwordless sudo for route — run `ssh-socks setup`",
                    )
                )
        # Check watchdog health if tunnel is running
        from ssh_socks_cli.tunnel import status as tunnel_status

        if tunnel_status().running:
            if watchdog_is_running():
                checks.append(Check("gateway watchdog", True, "running"))
            else:
                checks.append(
                    Check(
                        "gateway watchdog",
                        False,
                        "not running — route won't auto-update on network changes. "
                        "Restart with `ssh-socks restart`",
                    )
                )
    return checks
