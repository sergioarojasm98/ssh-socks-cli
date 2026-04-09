"""Configuration loading and validation."""

from __future__ import annotations

import contextlib
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ssh_socks_cli.paths import config_file


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or invalid."""


@dataclass
class TunnelConfig:
    """Tunnel connection settings."""

    host: str
    user: str
    port: int = 22
    identity_file: str | None = None
    local_port: int = 1080
    bind_address: str = "127.0.0.1"
    use_autossh: bool | None = None  # None = auto-detect
    compression: bool = True
    server_alive_interval: int = 30
    server_alive_count_max: int = 3
    connect_timeout: int = 10
    strict_host_key_checking: str = "accept-new"

    def identity_path(self) -> Path | None:
        """Return the expanded identity file path, if set."""
        if not self.identity_file:
            return None
        return Path(self.identity_file).expanduser()


@dataclass
class FirefoxConfig:
    """Firefox configuration settings."""

    proxy_dns: bool = True
    bypass_list: str = "localhost, 127.0.0.1"
    disable_webrtc: bool = True


@dataclass
class AppConfig:
    """Root configuration."""

    tunnel: TunnelConfig
    firefox: FirefoxConfig = field(default_factory=FirefoxConfig)


def load(path: Path | None = None) -> AppConfig:
    """Load configuration from disk.

    Raises ConfigError if the file is missing or malformed.
    """
    cfg_path = path or config_file()
    if not cfg_path.exists():
        raise ConfigError(f"Config file not found: {cfg_path}\nRun `ssh-socks init` to create it.")
    try:
        with cfg_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {cfg_path}: {e}") from e
    return from_dict(data)


def from_dict(data: dict[str, Any]) -> AppConfig:
    """Parse a raw dict into AppConfig with validation."""
    tunnel_data = data.get("tunnel")
    if not isinstance(tunnel_data, dict):
        raise ConfigError("Missing [tunnel] section in config.")
    for required in ("host", "user"):
        if required not in tunnel_data:
            raise ConfigError(f"Missing required tunnel.{required}")

    tunnel = TunnelConfig(**{k: v for k, v in tunnel_data.items() if k in _tunnel_fields()})
    firefox_data = data.get("firefox", {})
    firefox = FirefoxConfig(**{k: v for k, v in firefox_data.items() if k in _firefox_fields()})
    return AppConfig(tunnel=tunnel, firefox=firefox)


def _tunnel_fields() -> set[str]:
    return {f.name for f in fields(TunnelConfig)}


def _firefox_fields() -> set[str]:
    return {f.name for f in fields(FirefoxConfig)}


def save(cfg: AppConfig, path: Path | None = None) -> Path:
    """Write configuration to disk as TOML.

    We write by hand (no tomli-w dependency) — simple enough for this schema.
    """
    cfg_path = path or config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# ssh-socks-cli configuration",
        "# See https://github.com/sergioarojasm98/ssh-socks-cli for docs",
        "",
        "[tunnel]",
        f'host = "{cfg.tunnel.host}"',
        f'user = "{cfg.tunnel.user}"',
        f"port = {cfg.tunnel.port}",
    ]
    if cfg.tunnel.identity_file:
        lines.append(f'identity_file = "{cfg.tunnel.identity_file}"')
    lines.extend(
        [
            f"local_port = {cfg.tunnel.local_port}",
            f'bind_address = "{cfg.tunnel.bind_address}"',
            f"compression = {str(cfg.tunnel.compression).lower()}",
            f"server_alive_interval = {cfg.tunnel.server_alive_interval}",
            f"server_alive_count_max = {cfg.tunnel.server_alive_count_max}",
            f"connect_timeout = {cfg.tunnel.connect_timeout}",
            f'strict_host_key_checking = "{cfg.tunnel.strict_host_key_checking}"',
        ]
    )
    if cfg.tunnel.use_autossh is not None:
        lines.append(f"use_autossh = {str(cfg.tunnel.use_autossh).lower()}")
    lines.extend(
        [
            "",
            "[firefox]",
            f"proxy_dns = {str(cfg.firefox.proxy_dns).lower()}",
            f'bypass_list = "{cfg.firefox.bypass_list}"',
            f"disable_webrtc = {str(cfg.firefox.disable_webrtc).lower()}",
            "",
        ]
    )
    cfg_path.write_text("\n".join(lines), encoding="utf-8")
    with contextlib.suppress(OSError):
        cfg_path.chmod(0o600)
    return cfg_path
