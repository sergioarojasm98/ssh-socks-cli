"""Cross-platform XDG-compliant directory resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ssh-socks-cli"


def config_dir() -> Path:
    """Return the per-user config directory.

    Linux/macOS: ``$XDG_CONFIG_HOME/ssh-socks-cli`` or ``~/.config/ssh-socks-cli``
    Windows: ``%APPDATA%\\ssh-socks-cli``
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def state_dir() -> Path:
    """Return the per-user state directory (for PID files, logs, etc.).

    Linux/macOS: ``$XDG_STATE_HOME/ssh-socks-cli`` or ``~/.local/state/ssh-socks-cli``
    Windows: ``%LOCALAPPDATA%\\ssh-socks-cli``
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_NAME


def config_file() -> Path:
    """Return the path to the main config TOML file."""
    return config_dir() / "config.toml"


def pid_file() -> Path:
    """Return the path to the tunnel PID file."""
    return state_dir() / "tunnel.pid"


def log_file() -> Path:
    """Return the path to the tunnel log file."""
    return state_dir() / "tunnel.log"


def host_file() -> Path:
    """Return the path to the file storing the tunnel host for stop-time cleanup."""
    return state_dir() / "tunnel.host"


def watchdog_pid_file() -> Path:
    """Return the path to the watchdog PID file."""
    return state_dir() / "watchdog.pid"


SUDOERS_FILE = Path("/etc/sudoers.d/ssh-socks-route")
ROUTE_BINARY_MACOS = "/sbin/route"


def route_binary_linux() -> str:
    """Return the path to the ip binary on Linux."""
    for path in ("/sbin/ip", "/usr/sbin/ip", "/bin/ip", "/usr/bin/ip"):
        if Path(path).exists():
            return path
    return "/sbin/ip"


def ensure_dirs() -> None:
    """Create config and state directories if they don't exist."""
    config_dir().mkdir(parents=True, exist_ok=True)
    state_dir().mkdir(parents=True, exist_ok=True)
