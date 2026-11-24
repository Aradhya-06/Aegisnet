"""Client side of the test services: one HTTP GET, one DNS query, one TLS handshake.

  python -m communication.traffic http --host 10.10.5.2 --port 8080
  python -m communication.traffic dns  --host 10.10.5.2 --port 5353 --name aegisnet.lab
  python -m communication.traffic tls  --host 10.10.5.2 --port 8443
Prints one JSON line.
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import struct
import sys
import time

from .protocol import ProtocolError, ensure_lab_address


def http_get(host, port, timeout=3.0):
    """Plain HTTP/1.1 GET straight to the lab host.

    http.client is used on purpose: urllib would honour HTTP(S)_PROXY environment
    variables and send lab traffic to a proxy instead of the lab address."""
    import http.client
    ensure_lab_address(host)
    t = time.monotonic()
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/", headers={"User-Agent": "aegisnet-lab-client"})
        r = conn.getresponse()
        body = r.read(2000).decode("utf-8", "replace")
        return {"ok": True, "service": "http", "status_code": r.status, "body": body.strip(),
                "ms": round((time.monotonic() - t) * 1000, 2)}
    except (OSError, http.client.HTTPException) as exc:
        return {"ok": False, "service": "http", "error": str(exc)}
    finally:
        conn.close()


def dns_query(host, port, name="aegisnet.lab", timeout=2.0):
    ensure_lab_address(host)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    query = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t = time.monotonic()
    try:
        s.sendto(query, (host, port))
        data, _ = s.recvfrom(512)
        ip = socket.inet_ntoa(data[-4:]) if len(data) > len(query) else None
        return {"ok": True, "service": "dns", "name": name, "answer": ip, "ms": round((time.monotonic() - t) * 1000, 2)}
    except OSError as exc:
        return {"ok": False, "service": "dns", "error": str(exc)}
    finally:
        s.close()


def tls_handshake(host, port, timeout=3.0):
    ensure_lab_address(host)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE        # lab self-signed certificate, test traffic only
    t = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname="aegisnet.lab") as tls:   # SNI = aegisnet.lab
                tls.sendall(b"hello\n")
                body = tls.recv(1024).decode("utf-8", "replace")
                return {"ok": True, "service": "tls", "version": tls.version(), "cipher": tls.cipher()[0],
                        "body": body.strip(), "ms": round((time.monotonic() - t) * 1000, 2)}
    except (OSError, ssl.SSLError) as exc:
        return {"ok": False, "service": "tls", "error": str(exc)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("service", choices=["http", "dns", "tls"])
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--name", default="aegisnet.lab")
    a = p.parse_args(argv)
    try:
        if a.service == "http":
            res = http_get(a.host, a.port)
        elif a.service == "dns":
            res = dns_query(a.host, a.port, a.name)
        else:
            res = tls_handshake(a.host, a.port)
    except ProtocolError as exc:
        res = {"ok": False, "error": str(exc)}
    print(json.dumps(res))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
