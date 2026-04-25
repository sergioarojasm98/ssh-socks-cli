"""Gateway change watchdog for VPN bypass route auto-update.

When the user switches WiFi networks, the real gateway changes but the
bypass route still points to the old gateway. This module runs as a
detached background process, polling the gateway every N seconds and
updating the route when it changes. Combined with autossh's reconnection
logic, this makes network transitions seamless.

Usage as a detached process::

    python -m ssh_socks_cli.watchdog <host> [interval]
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time
from pathlib import Path

from ssh_socks_cli.paths import state_dir
from ssh_socks_cli.route import add_bypass_route, get_gateway, remove_bypass_route


def _watchdog_pid_file() -> Path:
    return state_dir() / "watchdog.pid"


def _log(msg: str, log_path: Path | None = None) -> None:
    """Append a timestamped watchdog log line."""
    line = f"[watchdog] {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n"
    if log_path:
        with contextlib.suppress(OSError), log_path.open("a", encoding="utf-8") as f:
            f.write(line)


def main(host: str, interval: int = 10, log_path: Path | None = None) -> None:
    """Run the gateway watchdog loop (blocking). Intended to run as a detached process."""
    # Write own PID
    pid_path = _watchdog_pid_file()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    # Handle SIGTERM for clean exit
    stop = False

    def _handle_term(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _handle_term)

    _log(f"started (PID {os.getpid()}, host={host}, interval={interval}s)", log_path)

    current_gateway = get_gateway()
    _log(f"initial gateway: {current_gateway or '(none)'}", log_path)

    no_gw_logged = False

    while not stop:
        # Sleep in small increments so SIGTERM is handled promptly
        deadline = time.monotonic() + interval
        while time.monotonic() < deadline and not stop:
            time.sleep(min(1.0, max(0, deadline - time.monotonic())))

        if stop:
            break

        new_gateway = get_gateway()

        if new_gateway is None:
            if not no_gw_logged:
                _log("no gateway detected, waiting for network...", log_path)
                no_gw_logged = True
            continue

        no_gw_logged = False

        if new_gateway != current_gateway:
            _log(f"gateway changed: {current_gateway} → {new_gateway}, updating bypass route", log_path)
            current_gateway = new_gateway

            try:
                rm_result = remove_bypass_route(host)
                _log(f"remove old route: {rm_result.detail}", log_path)
            except Exception as e:
                _log(f"error removing old route: {e}", log_path)

            try:
                add_result = add_bypass_route(host)
                _log(f"add new route: {add_result.detail}", log_path)
            except Exception as e:
                _log(f"error adding new route: {e}", log_path)

    _log("stopped", log_path)

    # Clean up PID file
    with contextlib.suppress(FileNotFoundError):
        pid_path.unlink()


def read_pid() -> int | None:
    """Read the watchdog PID from its PID file."""
    p = _watchdog_pid_file()
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def is_running() -> bool:
    """Check if the watchdog process is alive."""
    pid = read_pid()
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_watchdog() -> bool:
    """Stop the watchdog process. Returns True if it was running."""
    pid = read_pid()
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        with contextlib.suppress(FileNotFoundError):
            _watchdog_pid_file().unlink()
        return False
    except PermissionError:
        pass

    with contextlib.suppress(ProcessLookupError, OSError):
        os.kill(pid, signal.SIGTERM)

    # Wait for exit
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)

    with contextlib.suppress(FileNotFoundError):
        _watchdog_pid_file().unlink()
    return True


if __name__ == "__main__":
    from ssh_socks_cli.paths import log_file

    _host = sys.argv[1]
    _interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    main(_host, _interval, log_file())
