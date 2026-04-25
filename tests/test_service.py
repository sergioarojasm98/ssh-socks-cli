"""Tests for ssh_socks_cli.service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ssh_socks_cli.service import (
    ServiceError,
    ServiceStatus,
    _launchd_plist_content,
    _systemd_unit_content,
    install,
    status,
    uninstall,
)

# -------------------------------------------------------------------- unit content generation


def test_systemd_unit_content_has_required_sections() -> None:
    with patch("ssh_socks_cli.service._ssh_socks_bin", return_value="/usr/bin/ssh-socks"):
        content = _systemd_unit_content()
    assert "[Unit]" in content
    assert "[Service]" in content
    assert "[Install]" in content
    assert "/usr/bin/ssh-socks start" in content
    assert "/usr/bin/ssh-socks stop" in content
    assert "network-online.target" in content
    assert "Type=forking" in content


def test_launchd_plist_content_has_required_keys() -> None:
    with patch("ssh_socks_cli.service._ssh_socks_bin", return_value="/usr/bin/ssh-socks"):
        content = _launchd_plist_content()
    assert "<key>Label</key>" in content
    assert "<key>RunAtLoad</key>" in content
    assert "<true/>" in content
    assert "/usr/bin/ssh-socks" in content
    assert "<string>start</string>" in content


def test_launchd_plist_content_python_fallback() -> None:
    with patch(
        "ssh_socks_cli.service._ssh_socks_bin",
        return_value="/usr/bin/python3 -m ssh_socks_cli",
    ):
        content = _launchd_plist_content()
    assert "<string>/usr/bin/python3</string>" in content
    assert "<string>-m</string>" in content
    assert "<string>ssh_socks_cli</string>" in content


# -------------------------------------------------------------------- systemd install/uninstall


def test_systemd_install(tmp_path: Path) -> None:
    unit = tmp_path / "ssh-socks-cli.service"
    with (
        patch("ssh_socks_cli.service._systemd_unit_path", return_value=unit),
        patch("ssh_socks_cli.service._ssh_socks_bin", return_value="/usr/bin/ssh-socks"),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
        patch("ssh_socks_cli.service.sys") as mock_sys,
    ):
        mock_sys.platform = "linux"
        mock_run.return_value.returncode = 0
        result = _install_systemd_direct(unit)

    assert unit.exists()
    assert "[Service]" in unit.read_text()
    assert result == unit


def _install_systemd_direct(unit: Path) -> Path:
    """Helper to call the internal systemd install directly."""
    from ssh_socks_cli.service import _systemd_install

    return _systemd_install()


def test_systemd_uninstall(tmp_path: Path) -> None:
    unit = tmp_path / "ssh-socks-cli.service"
    unit.write_text("[Unit]\n")
    with (
        patch("ssh_socks_cli.service._systemd_unit_path", return_value=unit),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        from ssh_socks_cli.service import _systemd_uninstall

        result = _systemd_uninstall()
    assert not unit.exists()
    assert result == unit


def test_systemd_uninstall_not_installed(tmp_path: Path) -> None:
    unit = tmp_path / "ssh-socks-cli.service"
    with patch("ssh_socks_cli.service._systemd_unit_path", return_value=unit):
        from ssh_socks_cli.service import _systemd_uninstall

        with pytest.raises(ServiceError, match="not installed"):
            _systemd_uninstall()


# -------------------------------------------------------------------- systemd status


def test_systemd_status_installed(tmp_path: Path) -> None:
    unit = tmp_path / "ssh-socks-cli.service"
    unit.write_text("[Unit]\n")
    with (
        patch("ssh_socks_cli.service._systemd_unit_path", return_value=unit),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.stdout = "enabled\n"
        mock_run.return_value.returncode = 0
        from ssh_socks_cli.service import _systemd_status

        st = _systemd_status()
    assert st.installed is True
    assert st.platform == "systemd"
    assert "enabled" in st.detail


def test_systemd_status_not_installed(tmp_path: Path) -> None:
    unit = tmp_path / "ssh-socks-cli.service"
    with patch("ssh_socks_cli.service._systemd_unit_path", return_value=unit):
        from ssh_socks_cli.service import _systemd_status

        st = _systemd_status()
    assert st.installed is False
    assert st.detail == "not installed"


# -------------------------------------------------------------------- launchd install/uninstall


def test_launchd_install(tmp_path: Path) -> None:
    plist = tmp_path / "com.sergioarojasm98.ssh-socks-cli.plist"
    with (
        patch("ssh_socks_cli.service._launchd_plist_path", return_value=plist),
        patch("ssh_socks_cli.service._ssh_socks_bin", return_value="/usr/bin/ssh-socks"),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        from ssh_socks_cli.service import _launchd_install

        result = _launchd_install()

    assert plist.exists()
    assert "<key>Label</key>" in plist.read_text()
    assert result == plist


def test_launchd_uninstall(tmp_path: Path) -> None:
    plist = tmp_path / "com.sergioarojasm98.ssh-socks-cli.plist"
    plist.write_text("<plist/>\n")
    with (
        patch("ssh_socks_cli.service._launchd_plist_path", return_value=plist),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        from ssh_socks_cli.service import _launchd_uninstall

        result = _launchd_uninstall()
    assert not plist.exists()
    assert result == plist


# -------------------------------------------------------------------- launchd status


def test_launchd_status_installed(tmp_path: Path) -> None:
    plist = tmp_path / "com.sergioarojasm98.ssh-socks-cli.plist"
    plist.write_text("<plist/>\n")
    with (
        patch("ssh_socks_cli.service._launchd_plist_path", return_value=plist),
        patch("ssh_socks_cli.service.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        from ssh_socks_cli.service import _launchd_status

        st = _launchd_status()
    assert st.installed is True
    assert st.platform == "launchd"
    assert st.detail == "loaded"


def test_launchd_status_not_installed(tmp_path: Path) -> None:
    plist = tmp_path / "nonexistent.plist"
    with patch("ssh_socks_cli.service._launchd_plist_path", return_value=plist):
        from ssh_socks_cli.service import _launchd_status

        st = _launchd_status()
    assert st.installed is False


# -------------------------------------------------------------------- public API dispatch


def test_install_dispatches_linux() -> None:
    with (
        patch("ssh_socks_cli.service.sys") as mock_sys,
        patch("ssh_socks_cli.service._systemd_install", return_value=Path("/u")) as mock_install,
    ):
        mock_sys.platform = "linux"
        result = install()
    assert result == Path("/u")
    mock_install.assert_called_once()


def test_install_dispatches_darwin() -> None:
    with (
        patch("ssh_socks_cli.service.sys") as mock_sys,
        patch("ssh_socks_cli.service._launchd_install", return_value=Path("/p")) as mock_install,
    ):
        mock_sys.platform = "darwin"
        result = install()
    assert result == Path("/p")
    mock_install.assert_called_once()


def test_install_dispatches_win32() -> None:
    with (
        patch("ssh_socks_cli.service.sys") as mock_sys,
        patch("ssh_socks_cli.service._windows_install", return_value=Path("task")) as mock_install,
    ):
        mock_sys.platform = "win32"
        result = install()
    assert result == Path("task")
    mock_install.assert_called_once()


def test_install_unsupported_platform() -> None:
    with patch("ssh_socks_cli.service.sys") as mock_sys:
        mock_sys.platform = "freebsd"
        with pytest.raises(ServiceError, match="Unsupported platform"):
            install()


def test_uninstall_dispatches_linux() -> None:
    with (
        patch("ssh_socks_cli.service.sys") as mock_sys,
        patch(
            "ssh_socks_cli.service._systemd_uninstall", return_value=Path("/u")
        ) as mock_uninstall,
    ):
        mock_sys.platform = "linux"
        result = uninstall()
    assert result == Path("/u")
    mock_uninstall.assert_called_once()


def test_status_dispatches_linux() -> None:
    expected = ServiceStatus(installed=True, platform="systemd", service_path=None, detail="ok")
    with (
        patch("ssh_socks_cli.service.sys") as mock_sys,
        patch("ssh_socks_cli.service._systemd_status", return_value=expected),
    ):
        mock_sys.platform = "linux"
        result = status()
    assert result == expected


def test_status_unsupported_platform() -> None:
    with patch("ssh_socks_cli.service.sys") as mock_sys:
        mock_sys.platform = "freebsd"
        st = status()
    assert st.installed is False
    assert "unsupported" in st.detail


# -------------------------------------------------------------------- CLI integration


def test_cli_service_install() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app

    runner = CliRunner()
    with patch("ssh_socks_cli.cli.service.install", return_value=Path("/mock/service")):
        result = runner.invoke(app, ["service", "install"])
    assert result.exit_code == 0
    assert "installed" in result.output.lower()


def test_cli_service_uninstall() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app

    runner = CliRunner()
    with patch("ssh_socks_cli.cli.service.uninstall", return_value=Path("/mock/service")):
        result = runner.invoke(app, ["service", "uninstall"])
    assert result.exit_code == 0
    assert "removed" in result.output.lower()


def test_cli_service_status_installed() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app

    runner = CliRunner()
    st = ServiceStatus(
        installed=True, platform="systemd", service_path=Path("/u"), detail="enabled"
    )
    with patch("ssh_socks_cli.cli.service.status", return_value=st):
        result = runner.invoke(app, ["service", "status"])
    assert result.exit_code == 0
    assert "installed" in result.output.lower()
    assert "systemd" in result.output


def test_cli_service_status_not_installed() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app

    runner = CliRunner()
    st = ServiceStatus(installed=False, platform="systemd", service_path=None, detail="not installed")
    with patch("ssh_socks_cli.cli.service.status", return_value=st):
        result = runner.invoke(app, ["service", "status"])
    assert result.exit_code == 0
    assert "not installed" in result.output


def test_cli_service_install_error() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app

    runner = CliRunner()
    with patch(
        "ssh_socks_cli.cli.service.install",
        side_effect=ServiceError("systemctl not found"),
    ):
        result = runner.invoke(app, ["service", "install"])
    assert result.exit_code == 1
