"""Packet capture of the lab network with tcpdump, plus controlled traffic generation.

Safety rules enforced here AND in scripts/ns_exec.py:
  * capture runs inside a lab namespace (or `lo` on the host) - never on the user's
    real Wi-Fi/Ethernet interface;
  * the pcap may only be written under data/pcaps;
  * snaplen limits how many bytes of each packet are kept (default 512; 96 = headers only).
Root is needed for capture: in live mode that goes through the allow-listed helper.
"""
from __future__ import annotations

import json
import re
import signal
import subprocess
import tempfile
import time

from django.conf import settings

from communication import services as comm
from core import netenv
from core.models import Node

from . import parser
from .models import PacketCapture, PacketRecord

PCAP_DIR = settings.DATA_DIR / "pcaps"
_BPF_OK = re.compile(r"^[A-Za-z0-9.:/()!&|<>=_ -]{0,100}$")
_IFACE_OK = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")
TRAFFIC_TYPES = ["icmp", "tcp", "udp", "http", "dns", "tls"]
MAX_PACKETS = 2000


class CaptureError(ValueError):
    pass


def validate(node, iface, bpf, snaplen, duration):
    if node != "host" and node not in netenv.LAB_NODES:
        raise CaptureError("unknown node")
    if not _IFACE_OK.match(iface or ""):
        raise CaptureError("invalid interface name")
    if not _BPF_OK.match(bpf or "") or any(t.startswith("-") for t in (bpf or "").split()):
        raise CaptureError("capture filter may only contain words like: tcp udp icmp port 80 host 10.10.5.2 and or not")
    if not 64 <= snaplen <= 4096:
        raise CaptureError("snaplen must be between 64 and 4096")
    if not 2 <= duration <= 60:
        raise CaptureError("duration must be between 2 and 60 seconds")
    if node == "host" and iface != "lo":
        raise CaptureError("on the host only the loopback interface 'lo' may be captured (privacy: your real network traffic is off limits)")


def _targets():
    """(source node, destination ip, node for the traffic client) for the current mode."""
    if netenv.is_live():
        b = Node.objects.get(name="b")
        return "a", b.ip_primary
    return "host", "127.0.0.1"


def generate_traffic(kinds):
    """Send real test traffic of the requested kinds; returns a result list (nothing is faked)."""
    src, dst = _targets()
    needed = {"tcp": "tcp-b", "udp": "udp-b", "http": "http-b", "dns": "dns-b", "tls": "tls-b"}
    results = []
    for kind in kinds:
        if kind not in TRAFFIC_TYPES:
            continue
        try:
            if kind in needed:
                comm.start_service(needed[kind])
                time.sleep(0.2)
            if kind == "icmp":
                from monitoring import services as mon
                p = mon.ping(src if netenv.is_live() else "host", dst, count=3, timeout=1)
                results.append({"kind": "icmp", "ok": p["reachable"], "detail": f"{p['received']}/{p['sent']} replies"})
            elif kind in ("tcp", "udp"):
                port = 9001 if kind == "tcp" else 9002
                r = comm.run_client(src=src, proto=kind, host=dst, port=port, message="packet analyzer demo", count=3, timeout=2)
                results.append({"kind": kind, "ok": r.get("ok"), "detail": r.get("status")})
            else:
                port = {"http": 8080, "dns": 5353, "tls": 8443}[kind]
                argv = ["python3", "-m", "communication.traffic", kind, "--host", dst, "--port", str(port)]
                r = netenv.run_in_node(src if netenv.is_live() else "host", argv, timeout=15)
                try:
                    data = json.loads(r.stdout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    data = {"ok": False, "error": r.error or r.stderr.strip()}
                results.append({"kind": kind, "ok": data.get("ok"), "detail": data.get("error") or data.get("status_code") or data.get("answer") or data.get("version")})
        except (comm.ServiceError, netenv.PrivilegeError) as exc:
            results.append({"kind": kind, "ok": False, "detail": str(exc)})
    return results


def run_capture(node, iface, duration=8, bpf="", snaplen=512, traffic=()) -> PacketCapture:
    validate(node, iface, bpf, snaplen, duration)
    PCAP_DIR.mkdir(parents=True, exist_ok=True)
    cap = PacketCapture.objects.create(node=node, interface=iface, bpf_filter=bpf, snaplen=snaplen, duration=duration,
                                       mode="live" if netenv.is_live() and node != "host" else "host")
    path = PCAP_DIR / f"cap_{cap.pk}_{node}_{iface}.pcap"
    cap.pcap_path = str(path)
    argv = ["tcpdump", "-n", "-U", "--immediate-mode", "-i", iface, "-s", str(snaplen), "-w", str(path), *bpf.split()]
    errlog = tempfile.TemporaryFile()
    try:
        proc = netenv.popen_in_node(node, argv, stdout=subprocess.DEVNULL, stderr=errlog)
    except (netenv.PrivilegeError, OSError, ValueError) as exc:
        cap.status, cap.error = "failed", f"cannot start capture: {exc}"
        cap.save()
        return cap
    started = time.monotonic()
    for _ in range(40):                           # wait until tcpdump has opened the interface
        if path.exists() or proc.poll() is not None:
            break
        time.sleep(0.1)
    time.sleep(0.3)
    if traffic and proc.poll() is None:
        cap.traffic = generate_traffic(traffic)
    remaining = duration - (time.monotonic() - started)
    if traffic:
        remaining = min(remaining, 2.0)           # traffic is done: don't wait for the full duration
    if remaining > 0 and proc.poll() is None:
        time.sleep(remaining)
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)          # tcpdump flushes the file on SIGTERM
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    errlog.seek(0)
    err = errlog.read().decode(errors="replace").strip()
    errlog.close()
    if not path.exists() or path.stat().st_size < 24:
        cap.status = "failed"
        cap.error = (err.splitlines()[-1] if err else "tcpdump produced no file")[:400]
        cap.save()
        return cap
    try:
        rows = parser.parse_pcap(path, limit=MAX_PACKETS)
    except Exception as exc:  # scapy raises various errors on corrupt files
        cap.status, cap.error = "failed", f"could not parse pcap: {exc}"
        cap.save()
        return cap
    PacketRecord.objects.bulk_create([PacketRecord(capture=cap, **r) for r in rows], batch_size=500)
    cap.packet_count, cap.status = len(rows), "done"
    cap.save()
    return cap
