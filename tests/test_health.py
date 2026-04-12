"""Tests for ssh_socks_cli.health."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ssh_socks_cli.config import AppConfig, FirefoxConfig, TunnelConfig
from ssh_socks_cli.health import (
    Check,
    check_autossh,
    check_host_reachable,
    check_identity_file,
    check_local_port_free,
    check_ssh,
    detect_corporate_vpn,
    run_all,
)

# -------------------------------------------------------------------- Check dataclass


def test_check_str_ok() -> None:
    c = Check("test", True, "all good")
    assert "[green]" in str(c)
    assert "test" in str(c)
    assert "all good" in str(c)


def test_check_str_fail() -> None:
    c = Check("test", False, "broken")
    assert "[red]" in str(c)
    assert "broken" in str(c)


# -------------------------------------------------------------------- check_ssh


def test_check_ssh_found() -> None:
    with patch("ssh_socks_cli.health._which", return_value="/usr/bin/ssh"):
        result = check_ssh()
    assert result.ok is True
    assert result.name == "ssh"
    assert "/usr/bin/ssh" in result.detail


def test_check_ssh_not_found() -> None:
    with patch("ssh_socks_cli.health._which", return_value=None):
        result = check_ssh()
    assert result.ok is False
    assert "not found" in result.detail


# -------------------------------------------------------------------- check_autossh


def test_check_autossh_found() -> None:
    with patch("ssh_socks_cli.health._which", return_value="/usr/bin/autossh"):
        result = check_autossh()
    assert result.ok is True
    assert "/usr/bin/autossh" in result.detail


def test_check_autossh_not_found() -> None:
    with patch("ssh_socks_cli.health._which", return_value=None):
        result = check_autossh()
    assert result.ok is False
    assert "not found" in result.detail
    assert "optional" in result.detail


# -------------------------------------------------------------------- check_identity_file


def test_identity_file_none() -> None:
    result = check_identity_file(None)
    assert result.ok is True
    assert "none configured" in result.detail


def test_identity_file_missing(tmp_path: Path) -> None:
    result = check_identity_file(tmp_path / "nonexistent_key")
    assert result.ok is False
    assert "not found" in result.detail


def test_identity_file_valid(tmp_path: Path) -> None:
    key = tmp_path / "id_test"
    key.write_text("fake key")
    key.chmod(0o600)
    result = check_identity_file(key)
    assert result.ok is True
    assert str(key) in result.detail


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_identity_file_bad_permissions(tmp_path: Path) -> None:
    key = tmp_path / "id_test"
    key.write_text("fake key")
    key.chmod(0o644)
    result = check_identity_file(key)
    assert result.ok is False
    assert "permissions too open" in result.detail
    assert "chmod 600" in result.detail


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_identity_file_group_readable(tmp_path: Path) -> None:
    key = tmp_path / "id_test"
    key.write_text("fake key")
    key.chmod(0o640)
    result = check_identity_file(key)
    assert result.ok is False
    assert "permissions too open" in result.detail


# -------------------------------------------------------------------- check_host_reachable


def test_host_reachable_success() -> None:
    with patch("ssh_socks_cli.health.socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        result = check_host_reachable("example.com", 22)
    assert result.ok is True
    assert "TCP connect OK" in result.detail


def test_host_reachable_failure() -> None:
    with patch(
        "ssh_socks_cli.health.socket.create_connection",
        side_effect=OSError("Connection refused"),
    ):
        result = check_host_reachable("example.com", 22)
    assert result.ok is False
    assert "Connection refused" in result.detail


def test_host_reachable_timeout() -> None:
    with patch(
        "ssh_socks_cli.health.socket.create_connection",
        side_effect=OSError("timed out"),
    ):
        result = check_host_reachable("example.com", 22, timeout=1.0)
    assert result.ok is False
    assert "timed out" in result.detail


# -------------------------------------------------------------------- check_local_port_free


def test_local_port_free_success() -> None:
    with patch("ssh_socks_cli.health.socket.socket") as mock_socket_cls:
        mock_sock = mock_socket_cls.return_value.__enter__.return_value
        mock_sock.bind.return_value = None
        result = check_local_port_free("127.0.0.1", 1080)
    assert result.ok is True
    assert "is free" in result.detail


def test_local_port_in_use() -> None:
    with patch("ssh_socks_cli.health.socket.socket") as mock_socket_cls:
        mock_sock = mock_socket_cls.return_value.__enter__.return_value
        mock_sock.bind.side_effect = OSError("Address already in use")
        result = check_local_port_free("127.0.0.1", 1080)
    assert result.ok is False
    assert "not bindable" in result.detail
    assert "already in use" in result.detail


# -------------------------------------------------------------------- detect_corporate_vpn


def test_detect_vpn_found() -> None:
    with patch("ssh_socks_cli.health.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "PanGPA\nfirefox\nbash\n"
        result = detect_corporate_vpn()
    assert result.ok is True
    assert "GlobalProtect" in result.detail


def test_detect_vpn_multiple() -> None:
    with patch("ssh_socks_cli.health.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "PanGPA\nvpnagentd\nZSATunnel\nbash\n"
        result = detect_corporate_vpn()
    assert result.ok is True
    assert "GlobalProtect" in result.detail
    assert "Cisco AnyConnect" in result.detail
    assert "Zscaler" in result.detail


def test_detect_vpn_none() -> None:
    with patch("ssh_socks_cli.health.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "firefox\nbash\npython\n"
        result = detect_corporate_vpn()
    assert result.ok is True
    assert "none detected" in result.detail


def test_detect_vpn_subprocess_error() -> None:
    with patch(
        "ssh_socks_cli.health.subprocess.run",
        side_effect=OSError("command not found"),
    ):
        result = detect_corporate_vpn()
    assert result.ok is True
    assert "none detected" in result.detail


# -------------------------------------------------------------------- run_all


def test_run_all_without_config() -> None:
    with (
        patch("ssh_socks_cli.health._which", return_value="/usr/bin/ssh"),
        patch("ssh_socks_cli.health.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = ""
        checks = run_all(None)
    names = [c.name for c in checks]
    assert "ssh" in names
    assert "autossh" in names
    assert "config" in names
    assert "corporate VPN" in names
    # No config means no identity/host/port checks
    assert "identity file" not in names
    assert "host reachable" not in names
    assert "local port" not in names
    # Config check should fail
    config_check = next(c for c in checks if c.name == "config")
    assert config_check.ok is False


def test_run_all_with_config() -> None:
    cfg = AppConfig(
        tunnel=TunnelConfig(host="example.com", user="alice"),
        firefox=FirefoxConfig(),
    )
    with (
        patch("ssh_socks_cli.health._which", return_value="/usr/bin/ssh"),
        patch("ssh_socks_cli.health.socket.create_connection") as mock_conn,
        patch("ssh_socks_cli.health.socket.socket") as mock_socket_cls,
        patch("ssh_socks_cli.health.subprocess.run") as mock_run,
    ):
        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = lambda s, *a: None
        mock_socket_cls.return_value.__enter__.return_value.bind.return_value = None
        mock_run.return_value.stdout = ""
        checks = run_all(cfg)
    names = [c.name for c in checks]
    assert "ssh" in names
    assert "autossh" in names
    assert "config" in names
    assert "identity file" in names
    assert "host reachable" in names
    assert "local port" in names
    assert "corporate VPN" in names
    # Config check should pass
    config_check = next(c for c in checks if c.name == "config")
    assert config_check.ok is True
