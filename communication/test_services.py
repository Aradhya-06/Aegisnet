"""Controlled-lab application servers: HTTP, DNS and TLS.

They exist so the packet analyzer has real HTTP / DNS / TLS-handshake traffic to
look at, entirely inside the isolated lab network.

  python -m communication.test_services http --host 10.10.5.2 --port 8080
  python -m communication.test_services dns  --host 10.10.5.2 --port 5353
  python -m communication.test_services tls  --host 10.10.5.2 --port 8443
"""
from __future__ import annotations

import argparse
import datetime
import json
import socket
import ssl
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .protocol import DATA_DIR, ProtocolError, ensure_lab_address


def log(**kv):
    kv["t"] = round(time.time(), 3)
    print(json.dumps(kv), flush=True)


# ------------------------------------------------------------------ HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = "AegisNetTest/1.0"

    def do_GET(self):  # noqa: N802 (http.server naming)
        body = b"AegisNet lab HTTP server: hello from " + (self.server.server_address[0]).encode() + b"\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log(event="http", peer=self.client_address[0], request=self.requestline)


def serve_http(host, port, stop=None, ready=None):
    ensure_lab_address(host)
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.timeout = 0.5
    log(event="listening", service="http", host=host, port=port)
    if ready:
        ready.set()
    while not (stop and stop.is_set()):
        httpd.handle_request()
    httpd.server_close()


# ------------------------------------------------------------------ DNS
def build_dns_response(query: bytes, answer_ip: str):
    """Answer an A query for any name with `answer_ip` (minimal RFC 1035 encoder)."""
    if len(query) < 12:
        return None
    ident, flags, qd, *_ = struct.unpack("!HHHHHH", query[:12])
    if qd != 1:
        return None
    pos = 12
    while pos < len(query) and query[pos] != 0:
        pos += query[pos] + 1
    qend = pos + 1 + 4
    question = query[12:qend]
    qtype = struct.unpack("!H", query[qend - 4:qend - 2])[0]
    header = struct.pack("!HHHHHH", ident, 0x8180, 1, 1 if qtype == 1 else 0, 0, 0)
    if qtype != 1:
        return header + question
    answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton(answer_ip)
    return header + question + answer


def serve_dns(host, port, stop=None, ready=None):
    ensure_lab_address(host)
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((host, port))
    srv.settimeout(0.5)
    log(event="listening", service="dns", host=host, port=port)
    if ready:
        ready.set()
    while not (stop and stop.is_set()):
        try:
            data, addr = srv.recvfrom(512)
        except socket.timeout:
            continue
        resp = build_dns_response(data, host)
        if resp:
            srv.sendto(resp, addr)
            log(event="dns", peer=addr[0], bytes=len(data))
    srv.close()


# ------------------------------------------------------------------ TLS
def ensure_cert(certdir: Path):
    """Create a self-signed certificate for the lab TLS server (test use only)."""
    certdir.mkdir(parents=True, exist_ok=True)
    cert, key = certdir / "lab.crt", certdir / "lab.key"
    if cert.exists() and key.exists():
        return cert, key
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aegisnet.lab")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=365))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName("aegisnet.lab")]), critical=False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    key.chmod(0o600)
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def serve_tls(host, port, certdir, stop=None, ready=None):
    ensure_lab_address(host)
    cert, key = ensure_cert(certdir)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    srv.settimeout(0.5)
    log(event="listening", service="tls", host=host, port=port)
    if ready:
        ready.set()

    def one(conn, addr):
        try:
            with ctx.wrap_socket(conn, server_side=True) as tls:
                tls.settimeout(5)
                tls.recv(1024)
                tls.sendall(b"hello over TLS from the AegisNet lab\n")
                log(event="tls", peer=addr[0], version=tls.version(), cipher=tls.cipher()[0])
        except (ssl.SSLError, OSError) as exc:
            log(event="tls_error", peer=addr[0], error=str(exc))

    while not (stop and stop.is_set()):
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        threading.Thread(target=one, args=(conn, addr), daemon=True).start()
    srv.close()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("service", choices=["http", "dns", "tls"])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--cert", default=str(DATA_DIR / "certs" / "lab.crt"))
    a = p.parse_args(argv)
    try:
        if a.service == "http":
            serve_http(a.host, a.port)
        elif a.service == "dns":
            serve_dns(a.host, a.port)
        else:
            serve_tls(a.host, a.port, Path(a.cert).parent)
    except (ProtocolError, OSError) as exc:
        log(event="fatal", error=str(exc))
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
