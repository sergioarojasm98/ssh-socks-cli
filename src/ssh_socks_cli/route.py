"""Direct route management for the SSH tunnel host.

When the default route goes through a VPN or restricted network interface,
the SSH tunnel connection may be blocked or inspected. Adding a host-specific
route through the real network gateway (e.g. en0 on macOS) ensures the
tunnel reaches the exit server directly.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class RouteResult:
    success: bool
    gateway: str | None
    detail: str


def is_public_ip(host: str) -> bool:
    """Return True if host is a public (non-private, non-reserved) IP address.

    Returns False for hostnames — the caller should resolve them first or
    skip route management for non-IP hosts.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal (it's a hostname) — try to resolve it
        import socket

        try:
            resolved = socket.getaddrinfo(host, None, socket.AF_INET)
            if not resolved:
                return False
            addr = ipaddress.ip_address(resolved[0][4][0])
        except (socket.gaierror, OSError):
            return False

    return addr.is_global


def _get_gateway_macos() -> str | None:
    """Get the real (non-VPN) gateway on macOS via ipconfig getpacket en0.

    We use ipconfig instead of `route -n get default` because the latter
    returns the VPN gateway when a VPN client is active.
    """
    # Try common physical interfaces in order
    for iface in ("en0", "en1", "en2"):
        try:
            out = subprocess.run(
                ["ipconfig", "getpacket", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                continue
            # Look for: router (ip): {192.168.1.1}  or  router (ip_mult): {192.168.1.1}
            for line in out.stdout.splitlines():
                if "router" in line.lower():
                    # Extract IP from braces: {192.168.1.1} or plain
                    match = re.search(r"\{?([\d.]+)\}?", line.split(":")[-1])
                    if match:
                        return match.group(1)
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _get_gateway_linux() -> str | None:
    """Get the default gateway on Linux via ip route, preferring physical interfaces."""
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0:
            return None
        # Pick the first default route that's NOT a tun/vpn interface
        for line in out.stdout.splitlines():
            if "default" not in line:
                continue
            # Skip VPN tunnel interfaces
            dev_match = re.search(r"dev\s+(\S+)", line)
            if dev_match:
                dev = dev_match.group(1)
                if dev.startswith(("tun", "utun", "gpd", "cscotun", "wg")):
                    continue
            gw_match = re.search(r"via\s+([\d.]+)", line)
            if gw_match:
                return gw_match.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def get_gateway() -> str | None:
    """Detect the real (non-VPN) network gateway for the current platform."""
    if sys.platform == "darwin":
        return _get_gateway_macos()
    if sys.platform.startswith("linux"):
        return _get_gateway_linux()
    return None


def add_bypass_route(host: str) -> RouteResult:
    """Add a host-specific direct route for the tunnel host.

    Requires sudo on macOS/Linux. If sudo fails, returns a warning
    but does not raise — the tunnel might still work on some networks.
    """
    if sys.platform == "win32":
        return RouteResult(False, None, "VPN bypass route not supported on Windows")

    if not is_public_ip(host):
        return RouteResult(False, None, f"{host} is not a public IP — bypass not needed")

    gateway = get_gateway()
    if not gateway:
        return RouteResult(
            False, None, "could not detect real gateway — VPN bypass route not added"
        )

    if has_bypass_route(host):
        return RouteResult(True, gateway, f"bypass route for {host} already exists")

    if sys.platform == "darwin":
        cmd = ["sudo", "-n", "route", "add", "-host", host, gateway]
    else:
        cmd = ["sudo", "-n", "ip", "route", "add", f"{host}/32", "via", gateway]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return RouteResult(True, gateway, f"route added: {host} via {gateway}")
        # sudo -n failed (needs password) — try without -n as last resort
        cmd_interactive = [c for c in cmd if c != "-n"]
        result = subprocess.run(
            cmd_interactive, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return RouteResult(True, gateway, f"route added: {host} via {gateway}")
        return RouteResult(
            False,
            gateway,
            f"sudo failed (exit {result.returncode}): {result.stderr.strip()}. "
            f"Try: sudo route add -host {host} {gateway}",
        )
    except subprocess.TimeoutExpired:
        return RouteResult(
            False, gateway, f"sudo timed out — run manually: sudo route add -host {host} {gateway}"
        )
    except OSError as e:
        return RouteResult(False, gateway, f"failed to run route command: {e}")


def remove_bypass_route(host: str) -> RouteResult:
    """Remove the host-specific bypass route."""
    if sys.platform == "win32":
        return RouteResult(False, None, "VPN bypass route not supported on Windows")

    if not has_bypass_route(host):
        return RouteResult(True, None, f"no bypass route for {host} (already clean)")

    if sys.platform == "darwin":
        cmd = ["sudo", "-n", "route", "delete", "-host", host]
    else:
        cmd = ["sudo", "-n", "ip", "route", "del", f"{host}/32"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return RouteResult(True, None, f"route removed: {host}")
        # Try without -n
        cmd_interactive = [c for c in cmd if c != "-n"]
        result = subprocess.run(
            cmd_interactive, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return RouteResult(True, None, f"route removed: {host}")
        return RouteResult(False, None, f"failed to remove route: {result.stderr.strip()}")
    except (OSError, subprocess.SubprocessError):
        return RouteResult(False, None, f"failed to remove route for {host}")


_VPN_IFACE_PREFIXES = ("utun", "tun", "gpd", "cscotun", "wg")


def has_bypass_route(host: str) -> bool:
    """Check whether a host-specific bypass route exists via a physical interface.

    Returns False if the route goes through a VPN tunnel interface (utun*, tun*,
    gpd*, cscotun*, wg*), even if the destination matches — that's the VPN's own
    route, not ours.
    """
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["route", "-n", "get", host],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False

            has_dest = False
            iface: str | None = None

            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("destination:") and host in stripped:
                    has_dest = True
                if stripped.startswith("interface:"):
                    iface = stripped.split(":", 1)[1].strip()

            if not has_dest:
                return False

            # Reject routes via VPN tunnel interfaces
            return not (iface and iface.startswith(_VPN_IFACE_PREFIXES))
        else:
            result = subprocess.run(
                ["ip", "route", "show", f"{host}/32"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0 or host not in result.stdout:
                return False
            # Reject routes via VPN interfaces
            dev_match = re.search(r"dev\s+(\S+)", result.stdout)
            return not (dev_match and dev_match.group(1).startswith(_VPN_IFACE_PREFIXES))
    except (OSError, subprocess.SubprocessError):
        return False
