# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-06-15

### Added

- **Tunnel lifecycle** — `start`, `stop`, `restart`, `status`, `logs` commands to manage an SSH-based SOCKS5 tunnel in the background.
- **Firefox integration** — `firefox apply`, `reset`, `purge`, `show`, `profiles` commands that inject/remove a managed `user.js` block with DNS-leak protection, WebRTC hardening, DoH disabling, speculative connection blocking, and captive portal suppression.
- **`doctor` command** — environment diagnostics: checks for `ssh`/`autossh`, identity file permissions, host reachability, local port availability, and best-effort corporate VPN detection (GlobalProtect, AnyConnect, Zscaler).
- **`init` command** — interactive setup wizard that generates `~/.config/ssh-socks-cli/config.toml`.
- **`config show` / `config path`** — view current configuration.
- **Auto-reconnect** via `autossh` when available, with graceful fallback to plain `ssh` with aggressive keep-alives.
- **XDG-compliant paths** — config at `~/.config/ssh-socks-cli/`, state at `~/.local/state/ssh-socks-cli/` (Linux/macOS), `%APPDATA%` on Windows.
- **Cross-platform** — macOS, Linux, Windows (native OpenSSH client).
- **CI pipeline** — GitHub Actions with lint (ruff + mypy strict), test matrix (3 OS x 3 Python versions), and package build.

[0.1.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.1.0
