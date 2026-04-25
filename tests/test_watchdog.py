"""Tests for ssh_socks_cli.watchdog."""

from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import patch

from ssh_socks_cli.route import RouteResult
from ssh_socks_cli.watchdog import (
    _log,
    is_running,
    main,
    read_pid,
    stop_watchdog,
)

# -------------------------------------------------------------------- _log


def test_log_writes_to_file(tmp_path: Path) -> None:
    log = tmp_path / "test.log"
    _log("hello world", log)
    content = log.read_text()
    assert "[watchdog]" in content
    assert "hello world" in content


def test_log_no_path() -> None:
    # Should not raise
    _log("no file", None)


def test_log_appends(tmp_path: Path) -> None:
    log = tmp_path / "test.log"
    _log("first", log)
    _log("second", log)
    lines = log.read_text().splitlines()
    assert len(lines) == 2


# -------------------------------------------------------------------- read_pid / is_running


def test_read_pid_no_file(tmp_path: Path) -> None:
    with patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=tmp_path / "nope"):
        assert read_pid() is None


def test_read_pid_valid(tmp_path: Path) -> None:
    pid_file = tmp_path / "watchdog.pid"
    pid_file.write_text("12345")
    with patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file):
        assert read_pid() == 12345


def test_read_pid_invalid(tmp_path: Path) -> None:
    pid_file = tmp_path / "watchdog.pid"
    pid_file.write_text("not-a-number")
    with patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file):
        assert read_pid() is None


def test_is_running_no_pid() -> None:
    with patch("ssh_socks_cli.watchdog.read_pid", return_value=None):
        assert is_running() is False


def test_is_running_dead_process() -> None:
    with (
        patch("ssh_socks_cli.watchdog.read_pid", return_value=99999999),
        patch("ssh_socks_cli.watchdog.os.kill", side_effect=ProcessLookupError),
    ):
        assert is_running() is False


def test_is_running_alive() -> None:
    with (
        patch("ssh_socks_cli.watchdog.read_pid", return_value=12345),
        patch("ssh_socks_cli.watchdog.os.kill", return_value=None),
    ):
        assert is_running() is True


# -------------------------------------------------------------------- stop_watchdog


def test_stop_watchdog_not_running(tmp_path: Path) -> None:
    with patch("ssh_socks_cli.watchdog.read_pid", return_value=None):
        assert stop_watchdog() is False


def test_stop_watchdog_already_dead(tmp_path: Path) -> None:
    pid_file = tmp_path / "watchdog.pid"
    pid_file.write_text("99999999")
    with (
        patch("ssh_socks_cli.watchdog.read_pid", return_value=99999999),
        patch("ssh_socks_cli.watchdog.os.kill", side_effect=ProcessLookupError),
        patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file),
    ):
        assert stop_watchdog() is False


# -------------------------------------------------------------------- main loop


def test_main_writes_pid_and_exits(tmp_path: Path) -> None:
    """main() should write PID file and exit on SIGTERM."""
    pid_file = tmp_path / "watchdog.pid"
    log_file = tmp_path / "watchdog.log"

    call_count = 0

    def fake_get_gateway() -> str | None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            # Simulate SIGTERM by raising KeyboardInterrupt-like behavior
            os.kill(os.getpid(), signal.SIGTERM)
        return "192.168.1.1"

    with (
        patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file),
        patch("ssh_socks_cli.watchdog.get_gateway", side_effect=fake_get_gateway),
        patch("ssh_socks_cli.watchdog.add_bypass_route"),
        patch("ssh_socks_cli.watchdog.remove_bypass_route"),
        patch("ssh_socks_cli.watchdog.time.sleep"),
        patch("ssh_socks_cli.watchdog.time.monotonic", side_effect=[
            0, 100,  # first wait loop: start, past deadline
            0, 100,  # second wait loop
            0, 100,  # third wait loop (after SIGTERM)
        ]),
    ):
        main("8.8.8.8", interval=10, log_path=log_file)

    # PID file should be cleaned up on exit
    assert not pid_file.exists()
    log_content = log_file.read_text()
    assert "started" in log_content
    assert "stopped" in log_content


def test_main_detects_gateway_change(tmp_path: Path) -> None:
    """main() should update the route when the gateway changes."""
    pid_file = tmp_path / "watchdog.pid"
    log_file = tmp_path / "watchdog.log"

    gateways = iter(["192.168.1.1", "10.0.0.1"])
    call_count = 0

    def fake_get_gateway() -> str | None:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            os.kill(os.getpid(), signal.SIGTERM)
        return next(gateways, "10.0.0.1")

    with (
        patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file),
        patch("ssh_socks_cli.watchdog.get_gateway", side_effect=fake_get_gateway),
        patch("ssh_socks_cli.watchdog.remove_bypass_route", return_value=RouteResult(True, None, "removed")) as mock_rm,
        patch("ssh_socks_cli.watchdog.add_bypass_route", return_value=RouteResult(True, "10.0.0.1", "added")) as mock_add,
        patch("ssh_socks_cli.watchdog.time.sleep"),
        patch("ssh_socks_cli.watchdog.time.monotonic", side_effect=[
            0, 100,  # first wait
            0, 100,  # second wait
            0, 100,  # third wait (after SIGTERM)
        ]),
    ):
        main("8.8.8.8", interval=10, log_path=log_file)

    log_content = log_file.read_text()
    assert "gateway changed" in log_content
    mock_rm.assert_called_with("8.8.8.8")
    mock_add.assert_called_with("8.8.8.8")


def test_main_handles_no_network(tmp_path: Path) -> None:
    """main() should log once when network is gone and keep polling."""
    pid_file = tmp_path / "watchdog.pid"
    log_file = tmp_path / "watchdog.log"

    gateways = iter(["192.168.1.1", None, None])
    call_count = 0

    def fake_get_gateway() -> str | None:
        nonlocal call_count
        call_count += 1
        if call_count >= 4:
            os.kill(os.getpid(), signal.SIGTERM)
        return next(gateways, None)

    with (
        patch("ssh_socks_cli.watchdog._watchdog_pid_file", return_value=pid_file),
        patch("ssh_socks_cli.watchdog.get_gateway", side_effect=fake_get_gateway),
        patch("ssh_socks_cli.watchdog.remove_bypass_route"),
        patch("ssh_socks_cli.watchdog.add_bypass_route"),
        patch("ssh_socks_cli.watchdog.time.sleep"),
        patch("ssh_socks_cli.watchdog.time.monotonic", side_effect=[
            0, 100,  # first
            0, 100,  # second
            0, 100,  # third
            0, 100,  # fourth (after SIGTERM)
        ]),
    ):
        main("8.8.8.8", interval=10, log_path=log_file)

    log_content = log_file.read_text()
    assert "no gateway detected" in log_content
    # Should only log "no gateway" once (not spamming)
    assert log_content.count("no gateway detected") == 1


# -------------------------------------------------------------------- CLI integration


def test_cli_status_shows_watchdog() -> None:
    from typer.testing import CliRunner

    from ssh_socks_cli.cli import app
    from ssh_socks_cli.config import AppConfig, FirefoxConfig, TunnelConfig
    from ssh_socks_cli.tunnel import TunnelStatus

    runner = CliRunner()
    st = TunnelStatus(running=True, pid=42, binary=None, bind_address=None, local_port=None)
    cfg = AppConfig(
        tunnel=TunnelConfig(host="h", user="u"),
        firefox=FirefoxConfig(),
    )
    with (
        patch("ssh_socks_cli.cli.tunnel.status", return_value=st),
        patch("ssh_socks_cli.cli.config.load", return_value=cfg),
        patch("ssh_socks_cli.cli.watchdog.read_pid", return_value=555),
        patch("ssh_socks_cli.cli.watchdog.is_running", return_value=True),
    ):
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "555" in result.output
    assert "watchdog" in result.output.lower()
