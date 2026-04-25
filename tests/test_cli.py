"""Integration tests for ssh_socks_cli.cli using Typer's CliRunner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ssh_socks_cli import __version__
from ssh_socks_cli.cli import app
from ssh_socks_cli.config import AppConfig, ConfigError, FirefoxConfig, TunnelConfig
from ssh_socks_cli.health import Check
from ssh_socks_cli.tunnel import StartResult, StopResult, TunnelStatus

runner = CliRunner()


@pytest.fixture
def sample_cfg() -> AppConfig:
    return AppConfig(
        tunnel=TunnelConfig(
            host="proxy.example.com",
            user="alice",
            port=22,
            identity_file="~/.ssh/id_ed25519",
            local_port=1080,
            bind_address="127.0.0.1",
        ),
        firefox=FirefoxConfig(),
    )


# -------------------------------------------------------------------- version / help


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0 or result.exit_code == 2  # Typer no_args_is_help
    assert "ssh-socks" in result.output


# -------------------------------------------------------------------- start


def test_start_success(sample_cfg: AppConfig) -> None:
    start_result = StartResult(pid=12345, route=None)
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch("ssh_socks_cli.cli.tunnel.start", return_value=start_result),
    ):
        result = runner.invoke(app, ["start"])
    assert result.exit_code == 0
    assert "12345" in result.output
    assert "127.0.0.1:1080" in result.output


def test_start_no_config() -> None:
    with patch("ssh_socks_cli.cli.config.load", side_effect=ConfigError("not found")):
        result = runner.invoke(app, ["start"])
    assert result.exit_code == 1


def test_start_tunnel_error(sample_cfg: AppConfig) -> None:
    from ssh_socks_cli.tunnel import TunnelError

    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch("ssh_socks_cli.cli.tunnel.start", side_effect=TunnelError("port busy")),
    ):
        result = runner.invoke(app, ["start"])
    assert result.exit_code == 1


# -------------------------------------------------------------------- stop


def test_stop_running() -> None:
    stop_result = StopResult(stopped=True, route=None)
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=AppConfig(
            tunnel=TunnelConfig(host="h", user="u"), firefox=FirefoxConfig(),
        )),
        patch("ssh_socks_cli.cli.tunnel.stop", return_value=stop_result),
    ):
        result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0
    assert "stopped" in result.output.lower()


def test_stop_not_running() -> None:
    stop_result = StopResult(stopped=False, route=None)
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=AppConfig(
            tunnel=TunnelConfig(host="h", user="u"), firefox=FirefoxConfig(),
        )),
        patch("ssh_socks_cli.cli.tunnel.stop", return_value=stop_result),
    ):
        result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0
    assert "No running tunnel" in result.output


# -------------------------------------------------------------------- restart


def test_restart_success(sample_cfg: AppConfig) -> None:
    start_result = StartResult(pid=99999, route=None)
    with (
        patch("ssh_socks_cli.cli.tunnel.stop", return_value=StopResult(stopped=True, route=None)),
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch("ssh_socks_cli.cli.tunnel.start", return_value=start_result),
    ):
        result = runner.invoke(app, ["restart"])
    assert result.exit_code == 0
    assert "99999" in result.output


# -------------------------------------------------------------------- status


def test_status_running(sample_cfg: AppConfig) -> None:
    st = TunnelStatus(running=True, pid=42, binary=None, bind_address=None, local_port=None)
    with (
        patch("ssh_socks_cli.cli.tunnel.status", return_value=st),
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
    ):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "42" in result.output
    assert "127.0.0.1:1080" in result.output


def test_status_not_running() -> None:
    st = TunnelStatus(running=False, pid=None, binary=None, bind_address=None, local_port=None)
    with patch("ssh_socks_cli.cli.tunnel.status", return_value=st):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "not running" in result.output


def test_status_running_missing_config() -> None:
    st = TunnelStatus(running=True, pid=42, binary=None, bind_address=None, local_port=None)
    with (
        patch("ssh_socks_cli.cli.tunnel.status", return_value=st),
        patch("ssh_socks_cli.cli.config.load", side_effect=ConfigError("missing")),
    ):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "42" in result.output
    assert "config missing" in result.output


# -------------------------------------------------------------------- logs


def test_logs_no_file() -> None:
    with patch("ssh_socks_cli.cli.tunnel.log_path", return_value=Path("/nonexistent/log")):
        result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "No log file" in result.output


def test_logs_shows_content(tmp_path: Path) -> None:
    log = tmp_path / "tunnel.log"
    log.write_text("line1\nline2\nline3\n")
    with patch("ssh_socks_cli.cli.tunnel.log_path", return_value=log):
        result = runner.invoke(app, ["logs", "-n", "2"])
    assert result.exit_code == 0
    assert "line2" in result.output
    assert "line3" in result.output


# -------------------------------------------------------------------- doctor


def test_doctor_all_ok(sample_cfg: AppConfig) -> None:
    checks = [
        Check("ssh", True, "/usr/bin/ssh"),
        Check("autossh", True, "/usr/bin/autossh"),
        Check("config", True, "loaded"),
    ]
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch("ssh_socks_cli.cli.health.run_all", return_value=checks),
    ):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "All checks passed" in result.output


def test_doctor_some_fail() -> None:
    checks = [
        Check("ssh", True, "/usr/bin/ssh"),
        Check("autossh", False, "not found"),
    ]
    with (
        patch("ssh_socks_cli.cli.config.load", side_effect=ConfigError("nope")),
        patch("ssh_socks_cli.cli.health.run_all", return_value=checks),
    ):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Some checks failed" in result.output


def test_doctor_no_config() -> None:
    checks = [
        Check("ssh", True, "/usr/bin/ssh"),
        Check("config", False, "no config yet"),
    ]
    with (
        patch("ssh_socks_cli.cli.config.load", side_effect=ConfigError("missing")),
        patch("ssh_socks_cli.cli.health.run_all", return_value=checks),
    ):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1


# -------------------------------------------------------------------- config show / path


def test_config_show(sample_cfg: AppConfig) -> None:
    with patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "proxy.example.com" in result.output
    assert "alice" in result.output


def test_config_show_no_config() -> None:
    with patch("ssh_socks_cli.cli.config.load", side_effect=ConfigError("not found")):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1


def test_config_path() -> None:
    with patch("ssh_socks_cli.cli.paths.config_file", return_value=Path("/mock/config.toml")):
        result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert "/mock/config.toml" in result.output


# -------------------------------------------------------------------- firefox show


def test_firefox_show(sample_cfg: AppConfig) -> None:
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch(
            "ssh_socks_cli.cli.firefox.build_user_js_block",
            return_value="// mock block\n",
        ),
    ):
        result = runner.invoke(app, ["firefox", "show"])
    assert result.exit_code == 0
    assert "mock block" in result.output


# -------------------------------------------------------------------- firefox apply


def test_firefox_apply_yes_flag(sample_cfg: AppConfig, tmp_path: Path) -> None:
    from ssh_socks_cli.firefox import FirefoxProfile

    profile = FirefoxProfile(name="default", path=tmp_path, is_default=True, is_relative=True)
    written = tmp_path / "user.js"
    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch("ssh_socks_cli.cli.firefox.default_profile", return_value=profile),
        patch("ssh_socks_cli.cli.firefox.apply", return_value=written),
    ):
        result = runner.invoke(app, ["firefox", "apply", "--yes"])
    assert result.exit_code == 0
    assert "user.js" in result.output


def test_firefox_apply_no_profile(sample_cfg: AppConfig) -> None:
    from ssh_socks_cli.firefox import FirefoxError

    with (
        patch("ssh_socks_cli.cli.config.load", return_value=sample_cfg),
        patch(
            "ssh_socks_cli.cli.firefox.default_profile",
            side_effect=FirefoxError("no profiles"),
        ),
    ):
        result = runner.invoke(app, ["firefox", "apply", "--yes"])
    assert result.exit_code == 1


# -------------------------------------------------------------------- firefox reset


def test_firefox_reset_yes_flag(tmp_path: Path) -> None:
    from ssh_socks_cli.firefox import FirefoxProfile

    profile = FirefoxProfile(name="default", path=tmp_path, is_default=True, is_relative=True)
    written = tmp_path / "user.js"
    with (
        patch("ssh_socks_cli.cli.firefox.default_profile", return_value=profile),
        patch("ssh_socks_cli.cli.firefox.reset", return_value=written),
    ):
        result = runner.invoke(app, ["firefox", "reset", "--yes"])
    assert result.exit_code == 0
    assert "defaults block" in result.output


def test_firefox_reset_error(tmp_path: Path) -> None:
    from ssh_socks_cli.firefox import FirefoxError, FirefoxProfile

    profile = FirefoxProfile(name="default", path=tmp_path, is_default=True, is_relative=True)
    with (
        patch("ssh_socks_cli.cli.firefox.default_profile", return_value=profile),
        patch(
            "ssh_socks_cli.cli.firefox.reset",
            side_effect=FirefoxError("No ssh-socks-cli managed block"),
        ),
    ):
        result = runner.invoke(app, ["firefox", "reset", "--yes"])
    assert result.exit_code == 1


# -------------------------------------------------------------------- firefox purge


def test_firefox_purge_yes_flag(tmp_path: Path) -> None:
    from ssh_socks_cli.firefox import FirefoxProfile

    profile = FirefoxProfile(name="default", path=tmp_path, is_default=True, is_relative=True)
    written = tmp_path / "user.js"
    with (
        patch("ssh_socks_cli.cli.firefox.default_profile", return_value=profile),
        patch("ssh_socks_cli.cli.firefox.purge", return_value=written),
    ):
        result = runner.invoke(app, ["firefox", "purge", "--yes"])
    assert result.exit_code == 0
    assert "Purged" in result.output


# -------------------------------------------------------------------- firefox profiles


def test_firefox_profiles_found() -> None:
    from ssh_socks_cli.firefox import FirefoxProfile

    profiles = [
        FirefoxProfile(name="default", path=Path("/p/default"), is_default=True, is_relative=True),
        FirefoxProfile(name="work", path=Path("/p/work"), is_default=False, is_relative=True),
    ]
    with patch("ssh_socks_cli.cli.firefox.list_profiles", return_value=profiles):
        result = runner.invoke(app, ["firefox", "profiles"])
    assert result.exit_code == 0
    assert "default" in result.output
    assert "work" in result.output


def test_firefox_profiles_empty() -> None:
    with patch("ssh_socks_cli.cli.firefox.list_profiles", return_value=[]):
        result = runner.invoke(app, ["firefox", "profiles"])
    assert result.exit_code == 0
    assert "No Firefox profiles" in result.output


# -------------------------------------------------------------------- setup / unsetup


def test_setup_creates_sudoers(tmp_path: Path) -> None:
    fake_sudoers = tmp_path / "ssh-socks-route"
    with (
        patch("ssh_socks_cli.cli.paths.SUDOERS_FILE", fake_sudoers),
        patch("ssh_socks_cli.cli.sys.platform", "darwin"),
        patch("ssh_socks_cli.cli.subprocess.run") as mock_run,
        patch("ssh_socks_cli.cli.getpass.getuser", return_value="testuser"),
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert "Sudoers rule created" in result.output


def test_setup_already_exists(tmp_path: Path) -> None:
    fake_sudoers = tmp_path / "ssh-socks-route"
    fake_sudoers.write_text("testuser ALL=(ALL) NOPASSWD: /sbin/route\n")
    with (
        patch("ssh_socks_cli.cli.paths.SUDOERS_FILE", fake_sudoers),
        patch("ssh_socks_cli.cli.sys.platform", "darwin"),
        patch("ssh_socks_cli.cli.getpass.getuser", return_value="testuser"),
    ):
        result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert "already exists" in result.output


def test_setup_windows() -> None:
    with patch("ssh_socks_cli.cli.sys.platform", "win32"):
        result = runner.invoke(app, ["setup"])
    assert result.exit_code == 1


def test_unsetup_removes_file(tmp_path: Path) -> None:
    fake_sudoers = tmp_path / "ssh-socks-route"
    fake_sudoers.write_text("rule\n")
    with (
        patch("ssh_socks_cli.cli.paths.SUDOERS_FILE", fake_sudoers),
        patch("ssh_socks_cli.cli.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        result = runner.invoke(app, ["unsetup"])
    assert result.exit_code == 0
    assert "removed" in result.output.lower()


def test_unsetup_nothing_to_remove(tmp_path: Path) -> None:
    fake_sudoers = tmp_path / "nonexistent"
    with patch("ssh_socks_cli.cli.paths.SUDOERS_FILE", fake_sudoers):
        result = runner.invoke(app, ["unsetup"])
    assert result.exit_code == 0
    assert "nothing to remove" in result.output.lower()
