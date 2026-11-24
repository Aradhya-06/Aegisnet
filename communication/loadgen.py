"""UDP load generator for building the (optional) ML congestion dataset.

  python -m communication.loadgen --host 10.10.5.2 --port 9002 --mbps 8 --seconds 12
Sends 1000-byte datagrams at the requested offered load. Lab addresses only.
"""
import argparse
import json
import socket
import sys
import time

from .protocol import ProtocolError, ensure_lab_address

PAYLOAD = b"x" * 1000


def generate(host, port, mbps, seconds):
    ensure_lab_address(host)
    interval = len(PAYLOAD) * 8 / (mbps * 1e6)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sent, start = 0, time.perf_counter()
    next_t = start
    while True:
        now = time.perf_counter()
        if now - start >= seconds:
            break
        while next_t <= now:                      # catch up if we are behind schedule
            try:
                sock.sendto(PAYLOAD, (host, port))
            except (BlockingIOError, OSError):
                pass
            sent += 1
            next_t += interval
        time.sleep(0.0005)
    sock.close()
    return {"sent": sent, "seconds": round(time.perf_counter() - start, 2),
            "offered_mbps": round(sent * len(PAYLOAD) * 8 / (time.perf_counter() - start) / 1e6, 2)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--mbps", type=float, required=True)
    p.add_argument("--seconds", type=float, default=10)
    a = p.parse_args(argv)
    try:
        print(json.dumps(generate(a.host, a.port, max(0.1, min(a.mbps, 100)), max(1, min(a.seconds, 120)))))
    except ProtocolError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
