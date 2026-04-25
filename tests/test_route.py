"""Tests for ssh_socks_cli.route."""

from __future__ import annotations

from unittest.mock import patch

from ssh_socks_cli.route import (
    add_bypass_route,
    get_gateway,
    has_bypass_route,
    is_public_ip,
    remove_bypass_route,
)

# -------------------------------------------------------------------- is_public_ip


def test_public_ip_literal() -> None:
    assert is_public_ip("8.8.8.8") is True
    assert is_public_ip("1.1.1.1") is True
    assert is_public_ip("190.159.1.7") is True


def test_private_ip_literal() -> None:
    assert is_public_ip("10.0.0.1") is False
    assert is_public_ip("192.168.1.1") is False
    assert is_public_ip("172.16.0.1") is False
    assert is_public_ip("127.0.0.1") is False


def test_loopback_not_public() -> None:
    assert is_public_ip("127.0.0.1") is False


def test_link_local_not_public() -> None:
    assert is_public_ip("169.254.1.1") is False


def test_hostname_resolved_to_public() -> None:
    import socket as _socket

    with patch.object(_socket, "getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
        assert is_public_ip("example.com") is True


def test_hostname_resolved_to_private() -> None:
    import socket as _socket

    with patch.object(_socket, "getaddrinfo") as mock_gai:
        mock_gai.return_value = [(None, None, None, None, ("192.168.1.1", 0))]
        assert is_public_ip("my-local-server") is False


def test_hostname_resolution_fails() -> None:
    import socket as _socket

    with patch.object(
        _socket,
        "getaddrinfo",
        side_effect=_socket.gaierror("Name resolution failed"),
    ):
        assert is_public_ip("nonexistent.invalid") is False


# -------------------------------------------------------------------- get_gateway


def test_get_gateway_macos() -> None:
    ipconfig_output = (
        "op = BOOTREPLY\n"
        "htype = 1\n"
        "router (ip): {192.168.1.1}\n"
        "subnet_mask (ip): {255.255.255.0}\n"
    )
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ipconfig_output
        gw = get_gateway()
    assert gw == "192.168.1.1"


def test_get_gateway_macos_no_braces() -> None:
    ipconfig_output = "router (ip): 10.0.0.1\n"
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ipconfig_output
        gw = get_gateway()
    assert gw == "10.0.0.1"


def test_get_gateway_macos_fails() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        gw = get_gateway()
    assert gw is None


def test_get_gateway_linux() -> None:
    ip_route_output = (
        "default via 192.168.0.1 dev eth0 proto dhcp metric 100\n"
        "default via 10.0.0.1 dev tun0 proto static metric 50\n"
    )
    with (
        patch("ssh_socks_cli.route.sys.platform", "linux"),
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ip_route_output
        gw = get_gateway()
    assert gw == "192.168.0.1"  # picks eth0, skips tun0


def test_get_gateway_linux_skips_vpn_interfaces() -> None:
    ip_route_output = "default via 10.10.10.1 dev tun0\ndefault via 192.168.1.1 dev wlan0\n"
    with (
        patch("ssh_socks_cli.route.sys.platform", "linux"),
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ip_route_output
        gw = get_gateway()
    assert gw == "192.168.1.1"  # skips tun0


def test_get_gateway_windows() -> None:
    with patch("ssh_socks_cli.route.sys") as mock_sys:
        mock_sys.platform = "win32"
        gw = get_gateway()
    assert gw is None


# -------------------------------------------------------------------- add_bypass_route


def test_add_bypass_route_private_ip() -> None:
    result = add_bypass_route("192.168.1.1")
    assert result.success is False
    assert "not a public IP" in result.detail


def test_add_bypass_route_windows() -> None:
    with patch("ssh_socks_cli.route.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = add_bypass_route("8.8.8.8")
    assert result.success is False
    assert "not supported on Windows" in result.detail


def test_add_bypass_route_no_gateway() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.get_gateway", return_value=None),
        patch("ssh_socks_cli.route.is_public_ip", return_value=True),
    ):
        mock_sys.platform = "darwin"
        result = add_bypass_route("8.8.8.8")
    assert result.success is False
    assert "could not detect" in result.detail


def test_add_bypass_route_already_exists() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.get_gateway", return_value="192.168.1.1"),
        patch("ssh_socks_cli.route.is_public_ip", return_value=True),
        patch("ssh_socks_cli.route.has_bypass_route", return_value=True),
    ):
        mock_sys.platform = "darwin"
        result = add_bypass_route("8.8.8.8")
    assert result.success is True
    assert "already exists" in result.detail


def test_add_bypass_route_success_macos() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.get_gateway", return_value="192.168.1.1"),
        patch("ssh_socks_cli.route.is_public_ip", return_value=True),
        patch("ssh_socks_cli.route.has_bypass_route", return_value=False),
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        result = add_bypass_route("190.159.1.7")
    assert result.success is True
    assert "190.159.1.7" in result.detail
    assert "192.168.1.1" in result.detail


def test_add_bypass_route_sudo_fails() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.get_gateway", return_value="192.168.1.1"),
        patch("ssh_socks_cli.route.is_public_ip", return_value=True),
        patch("ssh_socks_cli.route.has_bypass_route", return_value=False),
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "sudo: a password is required"
        result = add_bypass_route("190.159.1.7")
    assert result.success is False
    assert "sudo failed" in result.detail


# -------------------------------------------------------------------- remove_bypass_route


def test_remove_bypass_route_not_present() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.has_bypass_route", return_value=False),
    ):
        mock_sys.platform = "darwin"
        result = remove_bypass_route("8.8.8.8")
    assert result.success is True
    assert "already clean" in result.detail


def test_remove_bypass_route_success() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.has_bypass_route", return_value=True),
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        result = remove_bypass_route("8.8.8.8")
    assert result.success is True
    assert "removed" in result.detail


def test_remove_bypass_route_windows() -> None:
    with patch("ssh_socks_cli.route.sys") as mock_sys:
        mock_sys.platform = "win32"
        result = remove_bypass_route("8.8.8.8")
    assert result.success is False
    assert "not supported" in result.detail


# -------------------------------------------------------------------- has_bypass_route


def test_has_bypass_route_macos_via_en0() -> None:
    """Route via en0 (physical) → True."""
    route_output = (
        "   route to: 190.159.1.7\n"
        "destination: 190.159.1.7\n"
        "    gateway: 192.168.1.1\n"
        "  interface: en0\n"
    )
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = route_output
        assert has_bypass_route("190.159.1.7") is True


def test_has_bypass_route_macos_via_utun_rejected() -> None:
    """Route via utun0 (VPN tunnel) → False — this is the VPN's route, not ours."""
    route_output = (
        "   route to: 190.159.1.7\n"
        "destination: 190.159.1.7\n"
        "    gateway: 172.28.153.127\n"
        "  interface: utun0\n"
        "      flags: <UP,GATEWAY,HOST,DONE,WASCLONED,IFSCOPE,IFREF,GLOBAL>\n"
    )
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = route_output
        assert has_bypass_route("190.159.1.7") is False


def test_has_bypass_route_macos_via_tun_rejected() -> None:
    """Route via tun0 (generic VPN) → False."""
    route_output = (
        "   route to: 8.8.8.8\n"
        "destination: 8.8.8.8\n"
        "    gateway: 10.0.0.1\n"
        "  interface: tun0\n"
    )
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = route_output
        assert has_bypass_route("8.8.8.8") is False


def test_has_bypass_route_macos_no_route() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "darwin"
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert has_bypass_route("190.159.1.7") is False


def test_has_bypass_route_linux_via_eth0() -> None:
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "linux"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "190.159.1.7 via 192.168.1.1 dev eth0\n"
        assert has_bypass_route("190.159.1.7") is True


def test_has_bypass_route_linux_via_tun_rejected() -> None:
    """Route via tun0 on Linux → False."""
    with (
        patch("ssh_socks_cli.route.sys") as mock_sys,
        patch("ssh_socks_cli.route.subprocess.run") as mock_run,
    ):
        mock_sys.platform = "linux"
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "190.159.1.7 via 10.0.0.1 dev tun0\n"
        assert has_bypass_route("190.159.1.7") is False
