"""TCP server (plain socket programming).

Life cycle shown here:  socket() -> setsockopt(SO_REUSEADDR) -> bind() -> listen()
-> accept() per client (3-way handshake already done by the kernel) -> recv/send
-> close() (FIN).  One thread per client.

Run:  python -m communication.tcp_server --host 10.10.5.2 --port 9001
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import threading
import time
from pathlib import Path

from .protocol import (DATA_DIR, ProtocolError, ensure_lab_address, recv_frame, safe_filename,
                       send_frame)


def log(**kv):
    kv["t"] = round(time.time(), 3)
    print(json.dumps(kv), flush=True)


def handle_frame(header: dict, body: bytes, state: dict, save_dir: Path):
    """Dispatch one request frame -> (reply_header, reply_body)."""
    kind = header.get("type")
    if kind == "msg":
        text = body.decode("utf-8", "replace")
        return {"type": "ack", "status": "ok", "received_bytes": len(body),
                "echo": text[:200], "server_time": time.time()}, b""
    if kind == "file":
        name = safe_filename(header.get("name", ""))
        save_dir.mkdir(parents=True, exist_ok=True)
        target = save_dir / f"{int(time.time())}_{name}"
        target.write_bytes(body)
        return {"type": "file_ack", "status": "ok", "saved_as": target.name, "received_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest()}, b""
    if kind == "bye":
        return None, b""
    return {"type": "error", "error": f"unknown request type {kind!r}"}, b""


def serve_client(conn: socket.socket, addr, save_dir: Path):
    state: dict = {}
    conn.settimeout(30)
    t0 = time.time()
    frames = 0
    try:
        while True:
            got = recv_frame(conn)
            if got is None:          # client sent FIN: orderly shutdown
                break
            header, body = got
            frames += 1
            reply, rbody = handle_frame(header, body, state, save_dir)
            if reply is None:
                break
            send_frame(conn, reply, rbody)
            log(event="request", peer=f"{addr[0]}:{addr[1]}", type=header.get("type"), bytes=len(body),
                status=reply.get("status", reply.get("type")))
    except (ProtocolError, ConnectionError, socket.timeout, ValueError) as exc:
        log(event="client_error", peer=f"{addr[0]}:{addr[1]}", error=str(exc))
    finally:
        conn.close()
        log(event="closed", peer=f"{addr[0]}:{addr[1]}", frames=frames, seconds=round(time.time() - t0, 3))


def serve(host: str, port: int, save_dir: Path, stop: threading.Event | None = None,
          ready: threading.Event | None = None):
    ensure_lab_address(host)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # allow quick restart
    srv.bind((host, port))
    srv.listen(16)
    srv.settimeout(0.5)                                         # so we can notice `stop`
    log(event="listening", host=host, port=port)
    if ready:
        ready.set()
    try:
        while not (stop and stop.is_set()):
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=serve_client, args=(conn, addr, save_dir), daemon=True).start()
    finally:
        srv.close()


def main(argv=None):
    p = argparse.ArgumentParser(description="AegisNet TCP test server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9001)
    p.add_argument("--save-dir", default=str(DATA_DIR / "received"))
    a = p.parse_args(argv)
    try:
        serve(a.host, a.port, Path(a.save_dir))
    except (ProtocolError, OSError) as exc:
        log(event="fatal", error=str(exc))
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
