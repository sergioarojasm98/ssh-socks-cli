"""Tests for ssh_socks_cli.tunnel (pure-function parts)."""

from __future__ import annotations

from pathlib import Path

from ssh_socks_cli.config import TunnelConfig
from ssh_socks_cli.tunnel import build_command


def test_build_command_basic() -> None:
    t = TunnelConfig(host="h.example.com", user="alice")
    cmd = build_command(t, "/usr/bin/ssh", is_autossh=False)
    assert cmd[0] == "/usr/bin/ssh"
    assert "-M" not in cmd  # no autossh-specific flag
    assert "-N" in cmd
    assert "-D" in cmd
    i = cmd.index("-D")
    assert cmd[i + 1] == "127.0.0.1:1080"
    assert cmd[-1] == "alice@h.example.com"


def test_build_command_autossh_adds_m0() -> None:
    t = TunnelConfig(host="h", user="u")
    cmd = build_command(t, "/usr/bin/autossh", is_autossh=True)
    assert cmd[:3] == ["/usr/bin/autossh", "-M", "0"]


def test_build_command_custom_port_and_bind() -> None:
    t = TunnelConfig(
        host="h",
        user="u",
        port=2222,
        bind_address="0.0.0.0",
        local_port=1337,
    )
    cmd = build_command(t, "ssh", is_autossh=False)
    assert "0.0.0.0:1337" in cmd
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "2222"


def test_build_command_no_p_flag_for_default_port() -> None:
    t = TunnelConfig(host="h", user="u", port=22)
    cmd = build_command(t, "ssh", is_autossh=False)
    assert "-p" not in cmd


def test_build_command_identity_file(tmp_path: Path) -> None:
    key = tmp_path / "id_test"
    key.write_text("fake")
    t = TunnelConfig(host="h", user="u", identity_file=str(key))
    cmd = build_command(t, "ssh", is_autossh=False)
    assert "-i" in cmd
    assert str(key) in cmd
    assert "IdentitiesOnly=yes" in cmd


def test_build_command_has_keepalive_options() -> None:
    t = TunnelConfig(host="h", user="u", server_alive_interval=45, server_alive_count_max=5)
    cmd = build_command(t, "ssh", is_autossh=False)
    assert "ServerAliveInterval=45" in cmd
    assert "ServerAliveCountMax=5" in cmd
    assert "ExitOnForwardFailure=yes" in cmd


def test_build_command_compression_toggle() -> None:
    t_on = TunnelConfig(host="h", user="u", compression=True)
    t_off = TunnelConfig(host="h", user="u", compression=False)
    assert "-C" in build_command(t_on, "ssh", is_autossh=False)
    assert "-C" not in build_command(t_off, "ssh", is_autossh=False)


def test_build_command_strict_host_key_checking() -> None:
    t = TunnelConfig(host="h", user="u", strict_host_key_checking="yes")
    cmd = build_command(t, "ssh", is_autossh=False)
    assert "StrictHostKeyChecking=yes" in cmd
