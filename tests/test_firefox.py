"""Tests for ssh_socks_cli.firefox."""

from __future__ import annotations

from pathlib import Path

import pytest

from ssh_socks_cli import firefox
from ssh_socks_cli.config import AppConfig, FirefoxConfig, TunnelConfig


@pytest.fixture
def sample_cfg() -> AppConfig:
    return AppConfig(
        tunnel=TunnelConfig(host="h", user="u", local_port=1080, bind_address="127.0.0.1"),
        firefox=FirefoxConfig(proxy_dns=True, disable_webrtc=True),
    )


def test_build_block_contains_essentials(sample_cfg: AppConfig) -> None:
    block = firefox.build_user_js_block(sample_cfg)
    assert firefox.BLOCK_BEGIN in block
    assert firefox.BLOCK_END in block
    assert 'user_pref("network.proxy.type", 1);' in block
    assert 'user_pref("network.proxy.socks", "127.0.0.1");' in block
    assert 'user_pref("network.proxy.socks_port", 1080);' in block
    assert 'user_pref("network.proxy.socks_version", 5);' in block
    assert 'user_pref("network.proxy.socks_remote_dns", true);' in block
    assert 'user_pref("network.proxy.failover_direct", false);' in block
    assert 'user_pref("media.peerconnection.enabled", false);' in block


def test_build_block_dns_leak_off(sample_cfg: AppConfig) -> None:
    sample_cfg.firefox.proxy_dns = False
    block = firefox.build_user_js_block(sample_cfg)
    assert 'user_pref("network.proxy.socks_remote_dns", false);' in block


def test_build_block_webrtc_opt_out(sample_cfg: AppConfig) -> None:
    sample_cfg.firefox.disable_webrtc = False
    block = firefox.build_user_js_block(sample_cfg)
    assert "media.peerconnection.enabled" not in block


def test_strip_managed_block_removes_only_our_block() -> None:
    before = (
        'user_pref("some.other", 1);\n'
        f"{firefox.BLOCK_BEGIN}\n"
        'user_pref("network.proxy.type", 1);\n'
        f"{firefox.BLOCK_END}\n"
        'user_pref("another.pref", "x");\n'
    )
    after = firefox._strip_managed_block(before)
    assert 'user_pref("some.other", 1);' in after
    assert 'user_pref("another.pref", "x");' in after
    assert firefox.BLOCK_BEGIN not in after
    assert 'user_pref("network.proxy.type", 1);' not in after


def test_strip_managed_block_noop_if_absent() -> None:
    content = 'user_pref("only.one", true);\n'
    assert firefox._strip_managed_block(content) == content


def test_apply_creates_user_js(sample_cfg: AppConfig, tmp_path: Path) -> None:
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    written = firefox.apply(sample_cfg, profile)
    assert written.exists()
    content = written.read_text()
    assert firefox.BLOCK_BEGIN in content
    assert "socks5" not in content.lower() or "socks_version" in content


def test_apply_preserves_existing_prefs(sample_cfg: AppConfig, tmp_path: Path) -> None:
    user_js = tmp_path / "user.js"
    user_js.write_text('user_pref("unrelated.setting", true);\n')
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    firefox.apply(sample_cfg, profile)
    content = user_js.read_text()
    assert 'user_pref("unrelated.setting", true);' in content
    assert firefox.BLOCK_BEGIN in content


def test_apply_is_idempotent(sample_cfg: AppConfig, tmp_path: Path) -> None:
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    firefox.apply(sample_cfg, profile)
    firefox.apply(sample_cfg, profile)
    content = (tmp_path / "user.js").read_text()
    # Only one managed block should exist
    assert content.count(firefox.BLOCK_BEGIN) == 1
    assert content.count(firefox.BLOCK_END) == 1


def test_apply_backs_up_existing(sample_cfg: AppConfig, tmp_path: Path) -> None:
    user_js = tmp_path / "user.js"
    user_js.write_text('user_pref("old.value", 42);\n')
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    firefox.apply(sample_cfg, profile)
    backups = list(tmp_path.glob("user.js.sshsocks-backup-*"))
    assert len(backups) == 1
    assert "old.value" in backups[0].read_text()


def test_reset_removes_block(sample_cfg: AppConfig, tmp_path: Path) -> None:
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    firefox.apply(sample_cfg, profile)
    firefox.reset(profile)
    content = (tmp_path / "user.js").read_text()
    assert firefox.BLOCK_BEGIN not in content


def test_reset_raises_if_no_block(tmp_path: Path) -> None:
    (tmp_path / "user.js").write_text('user_pref("x", 1);\n')
    profile = firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)
    with pytest.raises(firefox.FirefoxError, match="No ssh-socks-cli managed block"):
        firefox.reset(profile)
