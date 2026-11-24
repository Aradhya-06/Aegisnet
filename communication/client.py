"""TCP / UDP client. Prints ONE JSON result line so Django (or you) can read it.

Examples
  python -m communication.client --proto tcp --host 10.10.5.2 --port 9001 --message "hello"
  python -m communication.client --proto tcp --host 10.10.5.2 --port 9001 --file data/sample.txt
  python -m communication.client --proto tcp --host 10.10.5.2 --port 9001 --file f.bin
  python -m communication.client --proto udp --host 10.10.5.2 --port 9002 --message hi --count 10

Every step (connect, send, receive, FIN) is timed and recorded in "steps" - the
web UI shows them so the TCP life cycle is visible, not just a success message.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

from .protocol import DATA_DIR, ProtocolError, ensure_lab_address, recv_frame, send_frame


class Steps:
    def __init__(self):
        self.t0 = time.monotonic()
        self.items = []

    def add(self, text):
        self.items.append({"t_ms": round((time.monotonic() - self.t0) * 1000, 2), "text": text})


def _classify(exc):
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    return "error"


def tcp_send(host, port, *, kind="msg", message=None, filename=None, data=None, timeout=5.0):
    """Open a TCP connection, send one request, read the reply, close gracefully."""
    steps = Steps()
    result = {"proto": "tcp", "host": host, "port": port, "ok": False, "status": "error", "steps": steps.items}
    try:
        ensure_lab_address(host)
        payload = data if data is not None else (message or "").encode()
        result["bytes_sent"] = len(payload)
        result["sha256_sent"] = hashlib.sha256(payload).hexdigest()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        steps.add("socket(AF_INET, SOCK_STREAM) created")
        t = time.monotonic()
        try:
            sock.connect((host, port))                     # kernel performs SYN, SYN-ACK, ACK
        except OSError as exc:
            result["status"] = _classify(exc)
            result["error"] = f"connect() failed: {exc}"
            steps.add(f"connect() FAILED -> {result['status']} ({exc})")
            sock.close()
            return result
        result["connect_ms"] = round((time.monotonic() - t) * 1000, 3)
        result["local_addr"] = "%s:%d" % sock.getsockname()
        steps.add(f"connect() done in {result['connect_ms']} ms (3-way handshake SYN / SYN-ACK / ACK) from {result['local_addr']}")
        try:
            header = {"type": "file", "name": filename} if kind == "file" else {"type": "msg"}
            n = send_frame(sock, header, payload)
            steps.add(f"sendall(): {n} bytes written to the stream ({kind})")
            got = recv_frame(sock)
            if got is None:
                raise ConnectionError("server closed without replying")
            reply, _ = got
            steps.add(f"recv(): reply '{reply.get('type')}' received")
            result["response"] = reply
            result["ok"] = reply.get("status") == "ok"
            result["status"] = "success" if result["ok"] else "rejected"
            if kind == "file":
                result["sha256_received_by_server"] = reply.get("sha256")
                result["integrity_ok"] = reply.get("sha256") == result["sha256_sent"]
            # orderly termination: send FIN, then wait for the server's FIN
            sock.shutdown(socket.SHUT_WR)
            steps.add("shutdown(SHUT_WR): FIN sent - we have nothing more to send")
            try:
                if sock.recv(1) == b"":
                    steps.add("recv() returned b'': server's FIN received - connection closed in both directions")
            except (socket.timeout, OSError):
                steps.add("server did not close within the timeout")
        finally:
            sock.close()
            steps.add("close(): socket released")
    except ProtocolError as exc:
        result.update(status="refused", error=str(exc))
    except (OSError, ConnectionError, ValueError) as exc:
        result.update(status=_classify(exc), error=str(exc))
        steps.add(f"ERROR {exc}")
    result["total_ms"] = round((time.monotonic() - steps.t0) * 1000, 3)
    return result


def udp_send(host, port, message="hello", count=5, timeout=1.0, interval=0.05):
    """Send `count` independent datagrams; report which ones were answered."""
    steps = Steps()
    result = {"proto": "udp", "host": host, "port": port, "ok": False, "status": "error", "steps": steps.items,
              "datagrams": []}
    try:
        ensure_lab_address(host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        steps.add("socket(AF_INET, SOCK_DGRAM) created - no connect(), no handshake")
        for seq in range(1, count + 1):
            payload = json.dumps({"seq": seq, "msg": message}).encode()
            t = time.monotonic()
            try:
                sock.sendto(payload, (host, port))
                data, _ = sock.recvfrom(65535)
                rtt = round((time.monotonic() - t) * 1000, 3)
                reply = json.loads(data.decode())
                result["datagrams"].append({"seq": seq, "answered": True, "rtt_ms": rtt, "reply": reply})
                steps.add(f"datagram {seq}: sent {len(payload)} B, reply in {rtt} ms")
            except socket.timeout:
                result["datagrams"].append({"seq": seq, "answered": False, "rtt_ms": None})
                steps.add(f"datagram {seq}: NO REPLY within {timeout}s (lost, or server down) - UDP does not retransmit")
            except (ConnectionRefusedError, ConnectionResetError) as exc:
                result["datagrams"].append({"seq": seq, "answered": False, "rtt_ms": None, "error": "ICMP port unreachable"})
                steps.add(f"datagram {seq}: ICMP port unreachable ({exc})")
            time.sleep(interval)
        sock.close()
        sent = len(result["datagrams"])
        got = sum(1 for d in result["datagrams"] if d["answered"])
        result.update(sent=sent, received=got, lost=sent - got, loss_pct=round(100 * (sent - got) / sent, 1) if sent else 0)
        result["status"] = "success" if got == sent else ("partial" if got else "no_response")
        result["ok"] = got == sent
        if got:
            result["response"] = next(d["reply"] for d in result["datagrams"] if d["answered"])
    except ProtocolError as exc:
        result.update(status="refused", error=str(exc))
    except OSError as exc:
        result.update(status=_classify(exc), error=str(exc))
    result["total_ms"] = round((time.monotonic() - steps.t0) * 1000, 3)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="AegisNet TCP/UDP client")
    p.add_argument("--proto", choices=["tcp", "udp"], required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--message", default="")
    p.add_argument("--file")
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--timeout", type=float, default=5.0)
    a = p.parse_args(argv)
    if a.proto == "udp":
        res = udp_send(a.host, a.port, a.message or "hello", max(1, min(a.count, 100)), min(a.timeout, 10))
    else:
        data = filename = None
        kind = "msg"
        if a.file:
            path = Path(a.file)
            if not path.is_file():
                print(json.dumps({"ok": False, "status": "error", "error": f"file not found: {a.file}"}))
                return 1
            data, filename, kind = path.read_bytes(), path.name, "file"
        res = tcp_send(a.host, a.port, kind=kind, message=a.message, filename=filename, data=data,
                       timeout=min(a.timeout, 30))
    print(json.dumps(res))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
