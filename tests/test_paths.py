"""Tests for ssh_socks_cli.paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ssh_socks_cli import paths


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.skipif(sys.platform == "win32", reason="XDG paths are POSIX-only")
def test_config_dir_default_posix(clean_env: None) -> None:
    path = paths.config_dir()
    assert path.name == "ssh-socks-cli"
    assert ".config" in str(path)


@pytest.mark.skipif(sys.platform == "win32", reason="XDG paths are POSIX-only")
def test_state_dir_default_posix(clean_env: None) -> None:
    path = paths.state_dir()
    assert path.name == "ssh-socks-cli"
    assert os.sep.join([".local", "state"]) in str(path)


@pytest.mark.skipif(sys.platform == "win32", reason="XDG override is POSIX-only")
def test_xdg_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert paths.config_dir() == tmp_path / "cfg" / "ssh-socks-cli"
    assert paths.state_dir() == tmp_path / "state" / "ssh-socks-cli"


def test_config_file_is_under_config_dir() -> None:
    assert paths.config_file().parent == paths.config_dir()
    assert paths.config_file().name == "config.toml"


def test_pid_and_log_under_state_dir() -> None:
    assert paths.pid_file().parent == paths.state_dir()
    assert paths.log_file().parent == paths.state_dir()
    assert paths.pid_file().name == "tunnel.pid"
    assert paths.log_file().name == "tunnel.log"


def test_ensure_dirs_creates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    paths.ensure_dirs()
    assert paths.config_dir().exists()
    assert paths.state_dir().exists()
