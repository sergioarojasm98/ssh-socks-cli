"""Environment diagnostics for the `doctor` command."""

from __future__ import annotations

import shutil
import socket
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ssh_socks_cli.config import AppConfig


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


def detect_corporate_vpn() -> Check:
    """Best-effort detection of common corporate VPN clients.

    This is informational only — the tool works with or without a VPN active.
    """
    indicators: list[str] = []

    # Process name indicators (cross-platform via psutil would be cleaner,
    # but we avoid the dependency and use platform-specific probes).
    vpn_processes = {
        "GlobalProtect": ["PanGPA", "PanGPS", "GlobalProtect", "gpclient", "gpd"],
        "Cisco AnyConnect": ["vpnagentd", "vpnui", "vpn"],
        "Zscaler": ["ZSATunnel", "ZSAService", "Zscaler"],
    }

    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["ps", "-axco", "command"], capture_output=True, text=True, timeout=3
            ).stdout
        elif sys.platform.startswith("linux"):
            out = subprocess.run(
                ["ps", "-eo", "comm"], capture_output=True, text=True, timeout=3
            ).stdout
        elif sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout
        else:
            out = ""
    except (OSError, subprocess.SubprocessError):
        out = ""

    for vpn, procs in vpn_processes.items():
        for p in procs:
            if p.lower() in out.lower():
                indicators.append(vpn)
                break

    if indicators:
        return Check(
            "corporate VPN",
            True,
            f"detected: {', '.join(sorted(set(indicators)))} (informational)",
        )
    return Check("corporate VPN", True, "none detected (informational)")


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
    checks.append(detect_corporate_vpn())
    return checks
