"""UDP server: connectionless datagram echo.

socket(SOCK_DGRAM) -> bind() -> recvfrom() / sendto().  There is no listen(),
accept() or handshake: every datagram is independent, and the server keeps no
state about the sender. A lost datagram is simply never answered.

Run:  python -m communication.udp_server --host 10.10.5.2 --port 9002
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time

from .protocol import ProtocolError, ensure_lab_address


def log(**kv):
    kv["t"] = round(time.time(), 3)
    print(json.dumps(kv), flush=True)


def serve(host: str, port: int, stop: threading.Event | None = None, ready: threading.Event | None = None):
    ensure_lab_address(host)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((host, port))
    srv.settimeout(0.5)
    log(event="listening", proto="udp", host=host, port=port)
    if ready:
        ready.set()
    try:
        while not (stop and stop.is_set()):
            try:
                data, addr = srv.recvfrom(65535)
            except socket.timeout:
                continue
            try:
                msg = json.loads(data.decode())
                seq = msg.get("seq")
                reply = {"ack": True, "seq": seq, "echo": str(msg.get("msg", ""))[:200], "server_time": time.time()}
            except (ValueError, UnicodeDecodeError):
                reply = {"ack": False, "error": "datagram was not valid JSON", "bytes": len(data)}
            srv.sendto(json.dumps(reply).encode(), addr)
            log(event="datagram", peer=f"{addr[0]}:{addr[1]}", bytes=len(data), seq=reply.get("seq"))
    finally:
        srv.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="AegisNet UDP test server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9002)
    a = p.parse_args(argv)
    try:
        serve(a.host, a.port)
    except (ProtocolError, OSError) as exc:
        log(event="fatal", error=str(exc))
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
