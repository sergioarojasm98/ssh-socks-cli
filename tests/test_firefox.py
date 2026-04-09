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


@pytest.fixture
def profile(tmp_path: Path) -> firefox.FirefoxProfile:
    return firefox.FirefoxProfile(name="test", path=tmp_path, is_default=True, is_relative=True)


# -------------------------------------------------------------------- apply block content


def test_build_block_contains_essentials(sample_cfg: AppConfig) -> None:
    block = firefox.build_user_js_block(sample_cfg)
    assert firefox.BLOCK_BEGIN_APPLY in block
    assert firefox.BLOCK_END_APPLY in block
    assert 'user_pref("network.proxy.type", 1);' in block
    assert 'user_pref("network.proxy.socks", "127.0.0.1");' in block
    assert 'user_pref("network.proxy.socks_port", 1080);' in block
    assert 'user_pref("network.proxy.socks_version", 5);' in block
    assert 'user_pref("network.proxy.socks_remote_dns", true);' in block
    assert 'user_pref("network.proxy.socks5_remote_dns", true);' in block
    assert 'user_pref("network.proxy.failover_direct", false);' in block
    assert 'user_pref("network.proxy.allow_bypass", false);' in block
    assert 'user_pref("media.peerconnection.enabled", false);' in block


def test_build_block_disables_doh(sample_cfg: AppConfig) -> None:
    """Firefox's TRR (DoH) must be off to prevent racing the SOCKS tunnel."""
    block = firefox.build_user_js_block(sample_cfg)
    assert 'user_pref("network.trr.mode", 5);' in block


def test_build_block_disables_speculative(sample_cfg: AppConfig) -> None:
    block = firefox.build_user_js_block(sample_cfg)
    assert 'user_pref("network.http.speculative-parallel-limit", 0);' in block
    assert 'user_pref("network.predictor.enabled", false);' in block
    assert 'user_pref("network.prefetch-next", false);' in block


def test_build_block_disables_captive_portal(sample_cfg: AppConfig) -> None:
    block = firefox.build_user_js_block(sample_cfg)
    assert 'user_pref("network.captive-portal-service.enabled", false);' in block
    assert 'user_pref("network.connectivity-service.enabled", false);' in block


def test_build_block_dns_leak_off(sample_cfg: AppConfig) -> None:
    sample_cfg.firefox.proxy_dns = False
    block = firefox.build_user_js_block(sample_cfg)
    assert 'user_pref("network.proxy.socks_remote_dns", false);' in block
    assert 'user_pref("network.proxy.socks5_remote_dns", false);' in block


def test_build_block_webrtc_opt_out(sample_cfg: AppConfig) -> None:
    sample_cfg.firefox.disable_webrtc = False
    block = firefox.build_user_js_block(sample_cfg)
    assert "media.peerconnection.enabled" not in block


# -------------------------------------------------------------------- reset block content


def test_build_defaults_block_has_default_values() -> None:
    block = firefox.build_defaults_block()
    assert firefox.BLOCK_BEGIN_RESET in block
    assert firefox.BLOCK_END_RESET in block
    assert 'user_pref("network.proxy.type", 0);' in block
    assert 'user_pref("network.proxy.failover_direct", true);' in block
    assert 'user_pref("network.trr.mode", 0);' in block
    assert 'user_pref("media.peerconnection.enabled", true);' in block


# -------------------------------------------------------------------- strip helper


def test_strip_managed_block_removes_apply_block() -> None:
    before = (
        'user_pref("some.other", 1);\n'
        f"{firefox.BLOCK_BEGIN_APPLY}\n"
        'user_pref("network.proxy.type", 1);\n'
        f"{firefox.BLOCK_END_APPLY}\n"
        'user_pref("another.pref", "x");\n'
    )
    after = firefox._strip_managed_block(before)
    assert 'user_pref("some.other", 1);' in after
    assert 'user_pref("another.pref", "x");' in after
    assert firefox.BLOCK_BEGIN_APPLY not in after


def test_strip_managed_block_removes_reset_block() -> None:
    before = (
        'user_pref("keep.me", 1);\n'
        f"{firefox.BLOCK_BEGIN_RESET}\n"
        'user_pref("network.proxy.type", 0);\n'
        f"{firefox.BLOCK_END_RESET}\n"
    )
    after = firefox._strip_managed_block(before)
    assert 'user_pref("keep.me", 1);' in after
    assert firefox.BLOCK_BEGIN_RESET not in after


def test_strip_managed_block_removes_both() -> None:
    before = (
        f"{firefox.BLOCK_BEGIN_APPLY}\n"
        "apply stuff\n"
        f"{firefox.BLOCK_END_APPLY}\n"
        'user_pref("keep", 1);\n'
        f"{firefox.BLOCK_BEGIN_RESET}\n"
        "reset stuff\n"
        f"{firefox.BLOCK_END_RESET}\n"
    )
    after = firefox._strip_managed_block(before)
    assert firefox.BLOCK_BEGIN_APPLY not in after
    assert firefox.BLOCK_BEGIN_RESET not in after
    assert 'user_pref("keep", 1);' in after


def test_strip_managed_block_noop_if_absent() -> None:
    content = 'user_pref("only.one", true);\n'
    assert firefox._strip_managed_block(content) == content


# -------------------------------------------------------------------- apply()


def test_apply_creates_user_js(sample_cfg: AppConfig, profile: firefox.FirefoxProfile) -> None:
    written = firefox.apply(sample_cfg, profile)
    assert written.exists()
    content = written.read_text()
    assert firefox.BLOCK_BEGIN_APPLY in content
    assert "socks_version" in content


def test_apply_preserves_existing_prefs(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    (tmp_path / "user.js").write_text('user_pref("unrelated.setting", true);\n')
    firefox.apply(sample_cfg, profile)
    content = (tmp_path / "user.js").read_text()
    assert 'user_pref("unrelated.setting", true);' in content
    assert firefox.BLOCK_BEGIN_APPLY in content


def test_apply_is_idempotent(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    firefox.apply(sample_cfg, profile)
    firefox.apply(sample_cfg, profile)
    content = (tmp_path / "user.js").read_text()
    assert content.count(firefox.BLOCK_BEGIN_APPLY) == 1
    assert content.count(firefox.BLOCK_END_APPLY) == 1


def test_apply_replaces_reset_block(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    """Running apply after reset should remove the reset block, not duplicate."""
    firefox.apply(sample_cfg, profile)
    firefox.reset(profile)
    firefox.apply(sample_cfg, profile)
    content = (tmp_path / "user.js").read_text()
    assert firefox.BLOCK_BEGIN_RESET not in content
    assert content.count(firefox.BLOCK_BEGIN_APPLY) == 1


def test_apply_backs_up_existing(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    (tmp_path / "user.js").write_text('user_pref("old.value", 42);\n')
    firefox.apply(sample_cfg, profile)
    backups = list(tmp_path.glob("user.js.sshsocks-backup-*"))
    assert len(backups) == 1
    assert "old.value" in backups[0].read_text()


# -------------------------------------------------------------------- reset()


def test_reset_writes_defaults_block(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    firefox.apply(sample_cfg, profile)
    firefox.reset(profile)
    content = (tmp_path / "user.js").read_text()
    # Apply block is gone, reset block is present with defaults
    assert firefox.BLOCK_BEGIN_APPLY not in content
    assert firefox.BLOCK_BEGIN_RESET in content
    assert 'user_pref("network.proxy.type", 0);' in content
    assert 'user_pref("network.proxy.failover_direct", true);' in content


def test_reset_preserves_unrelated_prefs(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    (tmp_path / "user.js").write_text('user_pref("my.custom", "keep");\n')
    firefox.apply(sample_cfg, profile)
    firefox.reset(profile)
    content = (tmp_path / "user.js").read_text()
    assert 'user_pref("my.custom", "keep");' in content


def test_reset_raises_if_no_block(profile: firefox.FirefoxProfile, tmp_path: Path) -> None:
    (tmp_path / "user.js").write_text('user_pref("x", 1);\n')
    with pytest.raises(firefox.FirefoxError, match="No ssh-socks-cli managed block"):
        firefox.reset(profile)


# -------------------------------------------------------------------- purge()


def test_purge_removes_apply_block(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    firefox.apply(sample_cfg, profile)
    firefox.purge(profile)
    content = (tmp_path / "user.js").read_text()
    assert firefox.BLOCK_BEGIN_APPLY not in content
    assert firefox.BLOCK_BEGIN_RESET not in content


def test_purge_removes_reset_block(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    firefox.apply(sample_cfg, profile)
    firefox.reset(profile)
    firefox.purge(profile)
    content = (tmp_path / "user.js").read_text()
    assert firefox.BLOCK_BEGIN_APPLY not in content
    assert firefox.BLOCK_BEGIN_RESET not in content


def test_purge_preserves_unrelated_prefs(
    sample_cfg: AppConfig, profile: firefox.FirefoxProfile, tmp_path: Path
) -> None:
    (tmp_path / "user.js").write_text('user_pref("stays.put", "yes");\n')
    firefox.apply(sample_cfg, profile)
    firefox.purge(profile)
    content = (tmp_path / "user.js").read_text()
    assert 'user_pref("stays.put", "yes");' in content


def test_purge_raises_if_no_block(profile: firefox.FirefoxProfile, tmp_path: Path) -> None:
    (tmp_path / "user.js").write_text('user_pref("x", 1);\n')
    with pytest.raises(firefox.FirefoxError, match="No ssh-socks-cli managed block"):
        firefox.purge(profile)
