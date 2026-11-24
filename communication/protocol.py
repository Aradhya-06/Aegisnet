"""Tiny application protocol used on top of TCP by the AegisNet test client/server.

TCP is a byte STREAM with no message boundaries, so we frame messages ourselves:

    +----------------+------------------+----------------------+
    | 4 bytes (!I)   | JSON header      | body (header["size"])|
    | header length  | UTF-8            | raw bytes            |
    +----------------+------------------+----------------------+

This is plain Python socket programming - no Django involved - so the same file
is used by the server, the client and the unit tests.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import struct
from pathlib import Path

MAX_HEADER = 64 * 1024
MAX_BODY = 8 * 1024 * 1024          # 8 MB is plenty for lab files
LAB_NETS = [ipaddress.ip_network("10.10.0.0/16"), ipaddress.ip_network("127.0.0.0/8")]
DATA_DIR = Path(os.environ.get("AEGISNET_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


class ProtocolError(Exception):
    pass


def ensure_lab_address(host: str) -> str:
    """Refuse destinations outside the lab ranges (we never talk to the internet)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ProtocolError(f"destination must be an IP address, got {host!r}")
    if not any(ip in net for net in LAB_NETS):
        raise ProtocolError(f"{host} is outside the lab networks (10.10.0.0/16, 127.0.0.0/8)")
    return host


def safe_filename(name: str) -> str:
    base = os.path.basename(name or "")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80].strip("._")
    return base or "upload.bin"


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes or raise ConnectionError (TCP may deliver in pieces)."""
    chunks, got = [], 0
    while got < n:
        chunk = sock.recv(min(65536, n - got))
        if not chunk:
            raise ConnectionError("connection closed while reading")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def send_frame(sock: socket.socket, header: dict, body: bytes = b"") -> int:
    header = dict(header)
    header["size"] = len(body)
    raw = json.dumps(header, separators=(",", ":")).encode()
    sock.sendall(struct.pack("!I", len(raw)) + raw + body)
    return 4 + len(raw) + len(body)


def recv_frame(sock: socket.socket):
    """Return (header, body), or None if the peer closed cleanly between frames."""
    first = sock.recv(4)
    if not first:
        return None
    while len(first) < 4:
        more = sock.recv(4 - len(first))
        if not more:
            raise ConnectionError("connection closed inside frame length")
        first += more
    (hlen,) = struct.unpack("!I", first)
    if hlen > MAX_HEADER:
        raise ProtocolError("header too large")
    header = json.loads(recv_exact(sock, hlen).decode())
    size = int(header.get("size", 0))
    if size < 0 or size > MAX_BODY:
        raise ProtocolError("body size out of range")
    return header, recv_exact(sock, size) if size else b""
