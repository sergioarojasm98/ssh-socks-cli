# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-04-13

### Added

- **`ssh-socks setup`** — one-time command that creates a sudoers rule granting passwordless `sudo route` (macOS) or `sudo ip` (Linux), so route management works from non-interactive contexts.
- **`ssh-socks unsetup`** — removes the sudoers rule.
- **`init` suggests `setup`** — when `vpn_bypass = true`, the init flow prompts users to run `ssh-socks setup`.
- **`doctor` checks sudoers** — warns when `vpn_bypass` is enabled but the sudoers rule is missing.

## [0.4.1] - 2026-04-13

### Fixed

- **Bypass route detection** — `has_bypass_route()` now verifies the network interface, not just the destination. Previously, an unrelated host route over a tunnel interface (e.g., `utun0`) could be mistaken for our direct route via the physical interface.

## [0.4.0] - 2026-04-13

### Added

- **Gateway watchdog** — a background process that polls the network gateway every 10 seconds. When the gateway changes (e.g., switching WiFi networks), it automatically updates the host route. Combined with autossh's reconnection, network transitions are seamless.
- **`ssh-socks status`** now shows the watchdog PID when running.
- **`ssh-socks doctor`** checks watchdog health when `vpn_bypass` is enabled and the tunnel is running.

## [0.3.0] - 2026-04-12

### Added

- **Direct host route option (`vpn_bypass`)** — when enabled, `ssh-socks start` adds a host-specific direct route so the SSH tunnel reaches the exit server without following any custom default route. The route is cleaned up on `ssh-socks stop`. Supports macOS (`route add`) and Linux (`ip route add`).
- **`doctor` check** — verifies the host route is active when `vpn_bypass = true`.
- **`init` asks** — defaults to `true` when the configured host is a public IP.

## [0.2.0] - 2026-04-12

### Added

- **Auto-start service** — `service install`, `service uninstall`, `service status` commands to register the tunnel as a login service via systemd (Linux), launchd (macOS), or Windows Task Scheduler.

### Fixed

- **Firefox profile detection** — `default_profile()` now correctly prioritizes the `[Install<HASH>]` section in `profiles.ini` (Firefox 67+) over the legacy `Default=1` flag on `[Profile]` sections.

## [0.1.0] - 2025-06-15

### Added

- **Tunnel lifecycle** — `start`, `stop`, `restart`, `status`, `logs` commands.
- **Firefox integration** — `firefox apply`, `reset`, `purge`, `show`, `profiles` commands that inject/remove a managed `user.js` block with DNS-leak protection, WebRTC hardening, DoH disabling, speculative connection blocking, and captive portal suppression.
- **`doctor` command** — environment diagnostics: checks for `ssh`/`autossh`, identity file permissions, host reachability, local port availability.
- **`init` command** — interactive setup wizard that generates `~/.config/ssh-socks-cli/config.toml`.
- **`config show` / `config path`** — view current configuration.
- **Auto-reconnect** via `autossh` when available, with graceful fallback to plain `ssh` with aggressive keep-alives.
- **XDG-compliant paths** — config at `~/.config/ssh-socks-cli/`, state at `~/.local/state/ssh-socks-cli/` (Linux/macOS), `%APPDATA%` on Windows.
- **Cross-platform** — macOS, Linux, Windows (native OpenSSH client).
- **CI pipeline** — GitHub Actions with lint (ruff + mypy strict), test matrix (3 OS x 3 Python versions), and package build.

[0.5.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.5.0
[0.4.1]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.4.1
[0.4.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.4.0
[0.3.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.3.0
[0.2.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.2.0
[0.1.0]: https://github.com/sergioarojasm98/ssh-socks-cli/releases/tag/v0.1.0
