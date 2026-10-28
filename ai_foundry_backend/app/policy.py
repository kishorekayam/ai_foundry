# app/policy.py
"""Destination policy for user-entered database connections.

Users may connect their own test databases, but the platform must not become a way to probe internal networks.
Always blocked: link-local / cloud-metadata, unspecified, multicast and reserved ranges.
Blocked unless ALLOW_PRIVATE_TARGETS=true: loopback and private (RFC1918 / ULA) addresses.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional

from .config import get_settings

BLOCKED_NAMES = {"metadata.google.internal", "metadata", "instance-data"}


def check_destination(host: Optional[str], port: Optional[int], srv: bool = False) -> Optional[str]:
    """Returns a user-facing reason when the destination is refused, otherwise None."""
    host = (host or "").strip().lower()
    if not host or (not srv and not port) or (port and not (1 <= int(port) <= 65535)):
        return "Enter a valid host and port."
    if len(host) > 253 or any(ch in host for ch in " /\\@#?"):
        return "The host name contains characters that are not allowed."
    if host in BLOCKED_NAMES:
        return "Destination is not allowed by the network policy."
    if srv:  # mongodb+srv: the name is a DNS SRV record, there is no A record to inspect
        return None
    try:
        infos = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return "The host name could not be resolved."
    allow_private = get_settings().allow_private_targets
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            return "Destination is not allowed by the network policy."
        if (ip.is_private or ip.is_loopback) and not allow_private:
            return "Private and local network addresses are not allowed. Use a database reachable from the internet."
    return None
