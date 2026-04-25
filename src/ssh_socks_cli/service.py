"""Auto-start service management for systemd, launchd, and Windows Task Scheduler."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path


class ServiceError(Exception):
    """Raised when service operations fail."""


@dataclass
class ServiceStatus:
    installed: bool
    platform: str
    service_path: Path | None
    detail: str


# -------------------------------------------------------------------------- identifiers

_SYSTEMD_UNIT = "ssh-socks-cli.service"
_LAUNCHD_LABEL = "com.sergioarojasm98.ssh-socks-cli"
_WINDOWS_TASK_NAME = "ssh-socks-cli"


# -------------------------------------------------------------------------- path helpers


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / _SYSTEMD_UNIT


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


def _ssh_socks_bin() -> str:
    """Return the absolute path to the ssh-socks binary."""
    path = shutil.which("ssh-socks")
    if path:
        return path
    # Fallback: use python -m
    return f"{sys.executable} -m ssh_socks_cli"


# -------------------------------------------------------------------------- systemd (Linux)


def _systemd_unit_content() -> str:
    binary = _ssh_socks_bin()
    return textwrap.dedent(f"""\
        [Unit]
        Description=ssh-socks-cli SOCKS5 tunnel
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=forking
        ExecStart={binary} start
        ExecStop={binary} stop
        Restart=on-failure
        RestartSec=10

        [Install]
        WantedBy=default.target
    """)


def _systemd_install() -> Path:
    unit = _systemd_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_systemd_unit_content())

    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", _SYSTEMD_UNIT],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"systemctl failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("systemctl not found — is systemd available?") from e

    return unit


def _systemd_uninstall() -> Path:
    unit = _systemd_unit_path()
    if not unit.exists():
        raise ServiceError(f"Service not installed (no file at {unit})")

    try:
        subprocess.run(
            ["systemctl", "--user", "disable", _SYSTEMD_UNIT],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"systemctl failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("systemctl not found — is systemd available?") from e

    unit.unlink()
    return unit


def _systemd_status() -> ServiceStatus:
    unit = _systemd_unit_path()
    if not unit.exists():
        return ServiceStatus(
            installed=False,
            platform="systemd",
            service_path=None,
            detail="not installed",
        )
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", _SYSTEMD_UNIT],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.SubprocessError):
        state = "unknown (systemctl not available)"

    return ServiceStatus(
        installed=True,
        platform="systemd",
        service_path=unit,
        detail=state,
    )


# -------------------------------------------------------------------------- launchd (macOS)


def _launchd_plist_content() -> str:
    binary = _ssh_socks_bin()
    # If it's a "python -m" fallback, split into program arguments
    if " -m " in binary:
        parts = binary.split()
        program_args = "\n".join(f"        <string>{p}</string>" for p in parts)
    else:
        program_args = f"        <string>{binary}</string>"

    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
        {program_args}
                <string>start</string>
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <false/>
            <key>StandardOutPath</key>
            <string>/tmp/ssh-socks-cli.out.log</string>
            <key>StandardErrorPath</key>
            <string>/tmp/ssh-socks-cli.err.log</string>
        </dict>
        </plist>
    """)


def _launchd_install() -> Path:
    plist = _launchd_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_launchd_plist_content())

    try:
        subprocess.run(
            ["launchctl", "load", str(plist)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"launchctl load failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("launchctl not found") from e

    return plist


def _launchd_uninstall() -> Path:
    plist = _launchd_plist_path()
    if not plist.exists():
        raise ServiceError(f"Service not installed (no file at {plist})")

    try:
        subprocess.run(
            ["launchctl", "unload", str(plist)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"launchctl unload failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("launchctl not found") from e

    plist.unlink()
    return plist


def _launchd_status() -> ServiceStatus:
    plist = _launchd_plist_path()
    if not plist.exists():
        return ServiceStatus(
            installed=False,
            platform="launchd",
            service_path=None,
            detail="not installed",
        )

    try:
        result = subprocess.run(
            ["launchctl", "list", _LAUNCHD_LABEL],
            capture_output=True,
            text=True,
        )
        detail = "loaded" if result.returncode == 0 else "installed but not loaded"
    except (FileNotFoundError, subprocess.SubprocessError):
        detail = "unknown (launchctl not available)"

    return ServiceStatus(
        installed=True,
        platform="launchd",
        service_path=plist,
        detail=detail,
    )


# -------------------------------------------------------------------------- Windows Task Scheduler


def _windows_install() -> Path:
    binary = _ssh_socks_bin()
    # schtasks requires a single executable path; handle "python -m" fallback
    if " -m " in binary:
        parts = binary.split()
        exe = parts[0]
        args = " ".join(parts[1:]) + " start"
    else:
        exe = binary
        args = "start"

    try:
        subprocess.run(
            [
                "schtasks",
                "/Create",
                "/SC", "ONLOGON",
                "/TN", _WINDOWS_TASK_NAME,
                "/TR", f'"{exe}" {args}',
                "/F",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"schtasks failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("schtasks not found") from e

    return Path(f"Task Scheduler: {_WINDOWS_TASK_NAME}")


def _windows_uninstall() -> Path:
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", _WINDOWS_TASK_NAME, "/F"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ServiceError(f"schtasks failed: {e.stderr.strip()}") from e
    except FileNotFoundError as e:
        raise ServiceError("schtasks not found") from e

    return Path(f"Task Scheduler: {_WINDOWS_TASK_NAME}")


def _windows_status() -> ServiceStatus:
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _WINDOWS_TASK_NAME, "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and _WINDOWS_TASK_NAME in result.stdout:
            return ServiceStatus(
                installed=True,
                platform="windows",
                service_path=None,
                detail="registered",
            )
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    return ServiceStatus(
        installed=False,
        platform="windows",
        service_path=None,
        detail="not installed",
    )


# -------------------------------------------------------------------------- public API


def install() -> Path:
    """Install the auto-start service for the current platform."""
    if sys.platform.startswith("linux"):
        return _systemd_install()
    if sys.platform == "darwin":
        return _launchd_install()
    if sys.platform == "win32":
        return _windows_install()
    raise ServiceError(f"Unsupported platform: {sys.platform}")


def uninstall() -> Path:
    """Remove the auto-start service for the current platform."""
    if sys.platform.startswith("linux"):
        return _systemd_uninstall()
    if sys.platform == "darwin":
        return _launchd_uninstall()
    if sys.platform == "win32":
        return _windows_uninstall()
    raise ServiceError(f"Unsupported platform: {sys.platform}")


def status() -> ServiceStatus:
    """Check whether the auto-start service is installed."""
    if sys.platform.startswith("linux"):
        return _systemd_status()
    if sys.platform == "darwin":
        return _launchd_status()
    if sys.platform == "win32":
        return _windows_status()
    return ServiceStatus(
        installed=False,
        platform=sys.platform,
        service_path=None,
        detail=f"unsupported platform: {sys.platform}",
    )
