# ssh-socks-cli

> Route Firefox traffic **around** your corporate VPN via an SSH SOCKS5 tunnel — without wrestling with `ssh -D`, autossh flags, or Firefox's proxy pane.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey?style=for-the-badge)]()

## What problem does this solve?

You work on a corporate laptop with an **always-on VPN** — Palo Alto **GlobalProtect**, Cisco **AnyConnect**, **Zscaler**, or similar. Your employer routes every byte of traffic through their gateway, and you'd rather keep *personal* browsing (webmail, banking, social media, geo-restricted streaming) outside that tunnel. Or you're testing a service as an external user from the same machine. Or you just want separation between work and personal contexts.

The traditional workaround is:
1. SSH into a personal VPS or home server with `ssh -D 1080 user@host`
2. Open Firefox's network settings and manually configure SOCKS5 on 127.0.0.1:1080
3. Remember to enable "Proxy DNS when using SOCKS v5" (or leak your DNS through the corporate resolver)
4. Do it all over again every time you reboot

**ssh-socks-cli** automates all of that in one CLI.

## Features

- **One-command tunnel lifecycle** — `start`, `stop`, `status`, `restart`, `logs`
- **Firefox integration** — writes the correct `user.js` preferences with DNS-leak protection and WebRTC hardening, automatically detecting your default profile
- **Auto-reconnect** via `autossh` when available, falling back to plain `ssh` with aggressive keep-alives
- **`doctor` command** — diagnoses missing binaries, key file permissions, host reachability, and best-effort corporate VPN detection
- **XDG-compliant config** — lives at `~/.config/ssh-socks-cli/config.toml` (Linux/macOS) or `%APPDATA%\ssh-socks-cli\` (Windows)
- **Zero heavy dependencies** — no `paramiko`, no `cryptography`. Shells out to system `ssh`/`autossh`
- **Cross-platform** — macOS, Linux, Windows (native OpenSSH client)

## Prerequisites

- Python **3.11+**
- `ssh` (OpenSSH client). Any modern macOS, Linux, or Windows 10/11 already has it.
- `autossh` *(optional but recommended)* — for automatic reconnection when your network flaps
  - macOS: `brew install autossh`
  - Debian/Ubuntu: `sudo apt install autossh`
  - Fedora/RHEL: `sudo dnf install autossh`
  - Arch: `sudo pacman -S autossh`
- A reachable SSH server you own (VPS, home server, Raspberry Pi with port-forwarded SSH — anything that can accept an SSH connection and run `sshd`)
- An SSH key already configured for that server (password auth works too but keys are strongly recommended)

## Installation

```bash
pip install ssh-socks-cli
```

Or from source:

```bash
git clone https://github.com/sergioarojasm98/ssh-socks-cli.git
cd ssh-socks-cli
pip install -e .
```

## Quick start

```bash
# 1. Interactive setup — writes ~/.config/ssh-socks-cli/config.toml
ssh-socks init

# 2. Verify your environment is ready
ssh-socks doctor

# 3. Start the tunnel in the background
ssh-socks start

# 4. Configure Firefox to use it (detects default profile automatically)
ssh-socks firefox apply

# 5. Restart Firefox — done. Your Firefox traffic now exits from your SSH server.
```

To verify it's working, visit a site like `https://ifconfig.me` in Firefox. The IP should match your SSH server, not your corporate gateway.

## Command reference

| Command | Description |
|---|---|
| `ssh-socks init` | Interactively create the config file |
| `ssh-socks start` | Start the SOCKS5 tunnel in the background |
| `ssh-socks stop` | Stop the running tunnel |
| `ssh-socks restart` | Stop + start |
| `ssh-socks status` | Show tunnel status (running/stopped, PID, endpoint) |
| `ssh-socks logs [-f] [-n N]` | Show tunnel log (tail or follow) |
| `ssh-socks doctor` | Run environment diagnostics |
| `ssh-socks config show` | Print current configuration |
| `ssh-socks config path` | Print config file path |
| `ssh-socks firefox show` | Print the `user.js` block to stdout |
| `ssh-socks firefox apply` | Inject the block into the default profile's `user.js` |
| `ssh-socks firefox reset` | Remove our block from `user.js` |
| `ssh-socks firefox profiles` | List detected Firefox profiles |
| `ssh-socks --version` | Show version |

## Configuration file

Example `~/.config/ssh-socks-cli/config.toml`:

```toml
[tunnel]
host = "proxy.example.com"
user = "sergio"
port = 22
identity_file = "~/.ssh/id_ed25519"
local_port = 1080
bind_address = "127.0.0.1"
compression = true
server_alive_interval = 30
server_alive_count_max = 3
connect_timeout = 10
strict_host_key_checking = "accept-new"
# use_autossh = true   # omit to auto-detect

[firefox]
proxy_dns = true       # critical: prevents DNS leaks through corporate DNS
bypass_list = "localhost, 127.0.0.1"
disable_webrtc = true  # WebRTC can leak your real IP even through SOCKS5
```

## What does the Firefox block actually do?

`ssh-socks firefox apply` injects a clearly-delimited block into your profile's `user.js`:

```javascript
// BEGIN ssh-socks-cli managed block (do not edit manually)
user_pref("network.proxy.type", 1);
user_pref("network.proxy.socks", "127.0.0.1");
user_pref("network.proxy.socks_port", 1080);
user_pref("network.proxy.socks_version", 5);
user_pref("network.proxy.socks_remote_dns", true);
user_pref("network.proxy.no_proxies_on", "localhost, 127.0.0.1");
user_pref("network.proxy.failover_direct", false);
user_pref("network.proxy.allow_hijacking_localhost", true);
user_pref("media.peerconnection.enabled", false);
user_pref("network.dns.disablePrefetch", true);
// END ssh-socks-cli managed block
```

Each line has a reason:

| Pref | Why |
|---|---|
| `network.proxy.type=1` | Enable manual proxy mode |
| `network.proxy.socks*` | Point Firefox at `127.0.0.1:1080` as SOCKS v5 |
| `network.proxy.socks_remote_dns=true` | **Critical** — DNS resolution happens at the SSH server, not through your corporate resolver. Without this you leak every domain you visit. |
| `network.proxy.failover_direct=false` | If the tunnel drops, Firefox will NOT silently fall back to direct (i.e., the VPN). It will show a proxy error instead. This is what you want. |
| `media.peerconnection.enabled=false` | WebRTC can bypass the SOCKS proxy and leak your real LAN IP |
| `network.dns.disablePrefetch=true` | Prevents DNS prefetches going through the system resolver |

Your existing `user.js` is backed up to `user.js.sshsocks-backup-<timestamp>` before any changes. `ssh-socks firefox reset` removes only our block, leaving the rest of your prefs intact.

## Security notes

- **This is not a VPN.** It's a SOCKS5 proxy for Firefox only. Other apps on your machine still use the corporate VPN unless you configure them separately.
- **You control the exit server.** All Firefox traffic goes through *your* SSH host. Pick a host you trust.
- **Corporate policy.** Check whether your employer permits split-tunneling. This tool does not try to hide its existence — if your company runs DLP/EDR, they can likely see that you have an SSH session open. Use at your own discretion.
- **Key file permissions.** `ssh-socks doctor` will warn you if your private key has loose permissions. Fix with `chmod 600 ~/.ssh/id_ed25519`.
- **Host key checking.** Defaults to `accept-new` (TOFU on first connect, strict thereafter). You can tighten this in the config.

## Troubleshooting

**`ssh-socks start` exits immediately.**
Run `ssh-socks logs` — the SSH error is captured verbatim. The most common causes are wrong host/user, bad key, or the local port already in use.

**Firefox still uses the corporate VPN.**
1. Did you actually restart Firefox after `ssh-socks firefox apply`? `user.js` is only read on startup.
2. Go to `about:preferences#general` → Network Settings. It should show "Manual proxy configuration" with SOCKS host `127.0.0.1` and port `1080`.
3. Visit `about:config` and search `network.proxy.socks` — confirm the values are what you expect.

**DNS still resolves through my company.**
Confirm `network.proxy.socks_remote_dns` is `true` in `about:config`. Visit `https://dnsleaktest.com` in Firefox to confirm.

**The tunnel drops every few minutes.**
Install `autossh` — it will automatically reconnect. Check `ssh-socks doctor` to confirm it was picked up.

## Comparison with alternatives

| Option | Pros | Cons |
|---|---|---|
| Manual `ssh -D 1080` | Zero install | Forget on reboot, no status, no Firefox help, no auto-reconnect |
| FoxyProxy extension | Rich per-URL routing | You still need to run the SSH tunnel yourself |
| `ssh-socks-cli` | Tunnel lifecycle + Firefox config + doctor in one tool | You need an SSH server |
| Commercial VPN | Any browser, any traffic | Monthly cost, another company in your traffic path |

## Development

```bash
git clone https://github.com/sergioarojasm98/ssh-socks-cli.git
cd ssh-socks-cli
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## License

MIT — see [LICENSE](LICENSE).

## Author

Built by [Sergio Rojas](https://github.com/sergioarojasm98) — Senior Technical & AI Ops Engineer who got tired of typing `ssh -D 1080` every morning.
