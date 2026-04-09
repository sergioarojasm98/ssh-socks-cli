"""SSH/autossh tunnel lifecycle management."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ssh_socks_cli.config import AppConfig, TunnelConfig
from ssh_socks_cli.paths import log_file, pid_file, state_dir


class TunnelError(Exception):
    """Raised when tunnel lifecycle operations fail."""


@dataclass
class TunnelStatus:
    running: bool
    pid: int | None
    binary: str | None
    bind_address: str | None
    local_port: int | None


def _which_backend(use_autossh: bool | None) -> tuple[str, bool]:
    """Return (binary_path, is_autossh).

    use_autossh:
        True  -> require autossh
        False -> require plain ssh
        None  -> prefer autossh, fall back to ssh
    """
    autossh = shutil.which("autossh")
    ssh = shutil.which("ssh")

    if use_autossh is True:
        if not autossh:
            raise TunnelError("autossh not found in PATH (required by config).")
        return autossh, True
    if use_autossh is False:
        if not ssh:
            raise TunnelError("ssh not found in PATH.")
        return ssh, False
    # Auto mode
    if autossh:
        return autossh, True
    if ssh:
        return ssh, False
    raise TunnelError("Neither autossh nor ssh found in PATH.")


def build_command(tunnel: TunnelConfig, binary: str, is_autossh: bool) -> list[str]:
    """Build the argv for the SSH process.

    Notes on flag choices:
      -M 0               autossh: disable its own monitor port; rely on SSH keepalives
      -N                 no remote command (forwarding only)
      -D bind:port       dynamic SOCKS5 forwarding (the whole point)
      -C                 compression (optional, helps on slow links)
      -o ExitOnForwardFailure=yes  refuse to linger if the local bind fails
      -o ServerAliveInterval       client-side keepalive (triggers autossh reconnect)
      -o StrictHostKeyChecking=accept-new  TOFU on first connect, reject MITM after
      -o ConnectTimeout
    We intentionally do NOT pass -f here. We spawn detached from Python so we
    own the PID directly — mixing -f with Popen makes PID tracking unreliable.
    """
    cmd: list[str] = [binary]
    if is_autossh:
        cmd += ["-M", "0"]
    cmd += [
        "-N",
        "-D",
        f"{tunnel.bind_address}:{tunnel.local_port}",
        "-o",
        f"ServerAliveInterval={tunnel.server_alive_interval}",
        "-o",
        f"ServerAliveCountMax={tunnel.server_alive_count_max}",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        f"StrictHostKeyChecking={tunnel.strict_host_key_checking}",
        "-o",
        f"ConnectTimeout={tunnel.connect_timeout}",
    ]
    if tunnel.compression:
        cmd.append("-C")
    identity = tunnel.identity_path()
    if identity is not None:
        cmd += ["-i", str(identity), "-o", "IdentitiesOnly=yes"]
    if tunnel.port != 22:
        cmd += ["-p", str(tunnel.port)]
    cmd.append(f"{tunnel.user}@{tunnel.host}")
    return cmd


def _read_pid() -> int | None:
    p = pid_file()
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout
            return str(pid) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_pid(pid: int) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    pid_file().write_text(str(pid))


def _clear_pid() -> None:
    with contextlib.suppress(FileNotFoundError):
        pid_file().unlink()


def status() -> TunnelStatus:
    pid = _read_pid()
    if pid is None:
        return TunnelStatus(
            running=False, pid=None, binary=None, bind_address=None, local_port=None
        )
    if not _pid_alive(pid):
        _clear_pid()
        return TunnelStatus(
            running=False, pid=None, binary=None, bind_address=None, local_port=None
        )
    return TunnelStatus(running=True, pid=pid, binary=None, bind_address=None, local_port=None)


def start(cfg: AppConfig) -> int:
    """Start the tunnel in the background. Returns the PID of the spawned process."""
    current = status()
    if current.running:
        raise TunnelError(f"Tunnel already running (PID {current.pid}). Use `ssh-socks restart`.")

    binary, is_autossh = _which_backend(cfg.tunnel.use_autossh)
    cmd = build_command(cfg.tunnel, binary, is_autossh)
    state_dir().mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if is_autossh:
        # AUTOSSH_GATETIME=0: don't require the first connect to last N seconds
        # before considering autossh successful. Without this, quick failures
        # don't trigger retries.
        env.setdefault("AUTOSSH_GATETIME", "0")
        env.setdefault("AUTOSSH_POLL", "30")

    log_fp = log_file().open("ab")
    try:
        log_fp.write(
            f"\n--- ssh-socks-cli start: {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n".encode()
        )
        log_fp.write(f"cmd: {' '.join(cmd)}\n".encode())
        log_fp.flush()

        popen_kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_fp,
            "stderr": subprocess.STDOUT,
            "env": env,
            "close_fds": True,
        }
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            popen_kwargs["creationflags"] = 0x00000008 | 0x00000200  # type: ignore[assignment]
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **popen_kwargs)  # type: ignore[call-overload]
    finally:
        log_fp.close()

    # Give the process a moment to fail early (e.g., bad host, bad key).
    time.sleep(1.0)
    if proc.poll() is not None:
        _clear_pid()
        raise TunnelError(
            f"Tunnel exited immediately (code {proc.returncode}). "
            f"Check `ssh-socks logs` for details."
        )

    _write_pid(proc.pid)
    return proc.pid


def stop(timeout: float = 5.0) -> bool:
    """Stop the running tunnel. Returns True if a tunnel was stopped."""
    pid = _read_pid()
    if pid is None or not _pid_alive(pid):
        _clear_pid()
        return False

    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
            )
        else:
            # SIGTERM to the process group (autossh + its ssh child).
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(pid), signal.SIGTERM)

    # Wait for the process to disappear
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            _clear_pid()
            return True
        time.sleep(0.2)

    # Escalate
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    _clear_pid()
    return True


def log_path() -> Path:
    return log_file()
