"""Tiny TCP reachability probe used by the fault detector.

  python -m communication.probe tcp 10.10.5.2 9001 [--timeout 1]
Prints {"ok": bool, "connect_ms": float|null, "error": str|null}.
"""
import argparse
import json
import socket
import sys
import time

from .protocol import ProtocolError, ensure_lab_address


def tcp_probe(host, port, timeout=1.0):
    try:
        ensure_lab_address(host)
    except ProtocolError as exc:
        return {"ok": False, "connect_ms": None, "error": str(exc)}
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t = time.monotonic()
    try:
        s.connect((host, port))
        return {"ok": True, "connect_ms": round((time.monotonic() - t) * 1000, 3), "error": None}
    except OSError as exc:
        return {"ok": False, "connect_ms": None, "error": str(exc)}
    finally:
        s.close()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("kind", choices=["tcp"])
    p.add_argument("host")
    p.add_argument("port", type=int)
    p.add_argument("--timeout", type=float, default=1.0)
    a = p.parse_args(argv)
    res = tcp_probe(a.host, a.port, a.timeout)
    print(json.dumps(res))
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
