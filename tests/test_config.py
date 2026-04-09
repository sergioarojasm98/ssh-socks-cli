"""Tests for ssh_socks_cli.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from ssh_socks_cli.config import (
    AppConfig,
    ConfigError,
    FirefoxConfig,
    TunnelConfig,
    from_dict,
    load,
    save,
)


def test_from_dict_minimal() -> None:
    cfg = from_dict({"tunnel": {"host": "example.com", "user": "alice"}})
    assert cfg.tunnel.host == "example.com"
    assert cfg.tunnel.user == "alice"
    assert cfg.tunnel.port == 22
    assert cfg.tunnel.local_port == 1080
    assert cfg.firefox.proxy_dns is True


def test_from_dict_full() -> None:
    cfg = from_dict(
        {
            "tunnel": {
                "host": "bastion.example.com",
                "user": "bob",
                "port": 2222,
                "identity_file": "~/.ssh/bob_ed25519",
                "local_port": 1337,
                "bind_address": "0.0.0.0",
                "compression": False,
                "server_alive_interval": 60,
            },
            "firefox": {"proxy_dns": False, "bypass_list": "10.0.0.0/8"},
        }
    )
    assert cfg.tunnel.port == 2222
    assert cfg.tunnel.local_port == 1337
    assert cfg.tunnel.compression is False
    assert cfg.firefox.proxy_dns is False
    assert cfg.firefox.bypass_list == "10.0.0.0/8"


def test_from_dict_missing_tunnel_section() -> None:
    with pytest.raises(ConfigError, match="Missing \\[tunnel\\]"):
        from_dict({})


def test_from_dict_missing_host() -> None:
    with pytest.raises(ConfigError, match=r"tunnel\.host"):
        from_dict({"tunnel": {"user": "alice"}})


def test_from_dict_missing_user() -> None:
    with pytest.raises(ConfigError, match=r"tunnel\.user"):
        from_dict({"tunnel": {"host": "example.com"}})


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = AppConfig(
        tunnel=TunnelConfig(
            host="proxy.example.com",
            user="alice",
            port=2022,
            identity_file="~/.ssh/id_ed25519",
            local_port=1080,
        ),
        firefox=FirefoxConfig(proxy_dns=True),
    )
    path = tmp_path / "config.toml"
    save(cfg, path)
    assert path.exists()
    loaded = load(path)
    assert loaded.tunnel.host == "proxy.example.com"
    assert loaded.tunnel.user == "alice"
    assert loaded.tunnel.port == 2022
    assert loaded.tunnel.identity_file == "~/.ssh/id_ed25519"
    assert loaded.firefox.proxy_dns is True


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "does-not-exist.toml")


def test_load_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("this is = = invalid")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load(path)


def test_identity_path_expansion() -> None:
    cfg = TunnelConfig(host="x", user="y", identity_file="~/mykey")
    path = cfg.identity_path()
    assert path is not None
    assert "~" not in str(path)
    assert path.name == "mykey"


def test_identity_path_none() -> None:
    cfg = TunnelConfig(host="x", user="y")
    assert cfg.identity_path() is None
