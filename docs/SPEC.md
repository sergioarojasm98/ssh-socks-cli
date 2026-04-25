# ssh-socks-cli — Specification

## Problem statement

Routing Firefox through an SSH-based SOCKS5 tunnel is a small, well-known recipe — `ssh -D 1080 user@server` plus a few `network.proxy.*` prefs in Firefox. Doing it correctly (DNS leak prevention, auto-reconnect, persistent config, cross-platform) by hand is fragile and forgotten on reboot.

This tool wraps that recipe in a CLI. What you do with the resulting tunnel is your decision.

## Solution

A cross-platform Python CLI that:

1. **Manages an SSH-based SOCKS5 tunnel as a background service** (using `autossh` when available, falling back to `ssh` with keep-alives).
2. **Helps configure Firefox** to route traffic through the tunnel with a single command, including DNS-leak prevention.
3. **Runs anywhere Python runs** — macOS, Linux, Windows (WSL or native).

## Target users

- Anyone who already owns or can spin up a server reachable via SSH.
- Technical users comfortable with CLI tools (this is not a GUI product).

## User stories

### US1 — First-time setup
> As a new user, I want to run `ssh-socks init` and be walked through host, user, key path, and local port, so I don't have to hand-craft a config file.

### US2 — Start tunnel in background
> As a daily user, I want `ssh-socks start` to launch the tunnel in the background and return immediately, so I can keep using my terminal.

### US3 — Check status
> As a user, I want `ssh-socks status` to tell me whether the tunnel is running, on what PID, bound to which port, and since when.

### US4 — Stop tunnel cleanly
> As a user, I want `ssh-socks stop` to terminate the tunnel (and any autossh supervisor) without leaving zombies.

### US5 — Configure Firefox
> As a user, I want `ssh-socks firefox apply` to detect my default Firefox profile and inject the correct SOCKS5 preferences with DNS-leak protection.

### US6 — Roll back Firefox changes
> As a user, I want `ssh-socks firefox reset` to remove the preferences we added, restoring Firefox's previous state.

### US7 — Diagnose environment
> As a user, I want `ssh-socks doctor` to check that `ssh`/`autossh` exist, my key has the right permissions, the SSH host is reachable, and assess my network environment.

### US8 — Logs
> As a user, I want `ssh-socks logs` to tail the tunnel's stderr so I can debug connection issues.

## Functional requirements

| ID | Requirement |
|---|---|
| F1 | Configuration stored in TOML at XDG location (`~/.config/ssh-socks-cli/config.toml` on Linux/macOS, `%APPDATA%\ssh-socks-cli\config.toml` on Windows) |
| F2 | State (PID, log) stored at `~/.local/state/ssh-socks-cli/` (XDG state dir) |
| F3 | Use `autossh` when available; otherwise fall back to `ssh` with `ServerAliveInterval` |
| F4 | Default local bind: `127.0.0.1:1080` (configurable) |
| F5 | Non-interactive detached start: `-f -N -D` |
| F6 | PID file tracking with stale-PID detection |
| F7 | Firefox: write to `user.js` (persistent), not `prefs.js` (volatile) |
| F8 | Firefox: set `network.proxy.socks_remote_dns = true` to prevent DNS leaks |
| F9 | Firefox: back up existing `user.js` before modification |
| F10 | `doctor` checks: binaries, key file perms, host reachability, local port availability |

## Non-functional requirements

- **Zero runtime dependencies beyond Python stdlib and `typer` for CLI UX.** No paramiko, no cryptography libs — we shell out to `ssh`.
- **Python 3.11+** (for `tomllib` in stdlib).
- **Cross-platform**: macOS, Linux, Windows (native OpenSSH client).
- **No root required**: tunnel runs as user, Firefox config is per-user.
- **No network traffic from the CLI itself** (only `ssh` makes network calls).
- **Graceful degradation**: if `autossh` is missing, warn and use plain `ssh`.

## Out of scope (v0.1.0)

- GUI / system tray / menubar app
- Browsers other than Firefox (Chrome/Brave SOCKS5 works only via system proxy or extensions)
- Multi-tunnel / per-site routing
- Installing `autossh` for the user
- Managing SSH keys (generation, rotation)
- Packaging as a standalone binary (pyinstaller / pex) — v1 ships as pip package only

## CLI surface (v0.1.0)

```
ssh-socks init                  Interactive configuration
ssh-socks start                 Start tunnel in background
ssh-socks stop                  Stop running tunnel
ssh-socks restart               Stop + start
ssh-socks status                Show tunnel status
ssh-socks logs [--follow]       Show tunnel log (tail)
ssh-socks doctor                Diagnose environment
ssh-socks config show           Print current config
ssh-socks config path           Print config file path
ssh-socks firefox show          Print user.js snippet to stdout
ssh-socks firefox apply         Write snippet to default profile's user.js
ssh-socks firefox reset         Remove our snippet from user.js
ssh-socks firefox profiles      List Firefox profiles
ssh-socks --version
ssh-socks --help
```

## Success criteria for v0.1.0

- A user on macOS with Homebrew `autossh` installed can go from `pip install ssh-socks-cli` to a working Firefox SOCKS5 tunnel in under 5 minutes.
- `ssh-socks start` survives network drops for at least 15 minutes without manual restart (via autossh reconnect).
- `ssh-socks firefox apply` produces a Firefox that does NOT leak DNS through the local network.
- Running `ssh-socks doctor` on a fresh machine tells the user exactly which dependency is missing.
