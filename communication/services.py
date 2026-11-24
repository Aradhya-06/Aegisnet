"""Glue between Django and the standalone socket programs.

Clients and servers are separate processes (python -m communication.client ...).
In live mode they run INSIDE the lab namespaces, so their packets really cross
the virtual routers and can be captured by the packet analyzer.
"""
from __future__ import annotations

import json
import re
import uuid

from django.conf import settings

from core import netenv, processes
from core import topology_def
from core.models import Node

from .models import TransferSession

UPLOAD_DIR = settings.DATA_DIR / "uploads"
MAX_UPLOAD = 4 * 1024 * 1024
HOST_SOURCE = "host"


class ServiceError(ValueError):
    pass


def service_catalog():
    """name -> dict(node, proto, port, host, kind, argv) valid for the current mode."""
    live = netenv.is_live()
    nodes = {n.name: n for n in Node.objects.all()}
    out = {}
    for name, node, proto, port in topology_def.SERVICES:
        if live:
            ip, run_node = nodes[node].ip_primary, node
        else:
            if node != "b":
                continue                        # on a single host only one copy of each service fits
            ip, run_node = "127.0.0.1", "host"
        kind = name.split("-")[0]
        if kind in ("tcp", "udp"):
            argv = [f"communication.{kind}_server", "--host", ip, "--port", str(port)]
            if kind == "tcp":
                argv += ["--save-dir", str(settings.DATA_DIR / "received")]
        else:
            argv = ["communication.test_services", kind, "--host", ip, "--port", str(port)]
            if kind == "tls":
                argv += ["--cert", str(settings.DATA_DIR / "certs" / "lab.crt")]
        out[name] = dict(name=name, node=run_node, proto=proto, port=port, host=ip, kind=kind, argv=argv,
                         label=f"{kind.upper()} server on {nodes[node].label if live else 'this host'}")
    return out


def services_status():
    cat = service_catalog()
    rows = []
    for name, s in cat.items():
        rows.append({**{k: s[k] for k in ("name", "node", "proto", "port", "host", "label")},
                     "running": processes.is_running(name)})
    return rows


def start_service(name):
    cat = service_catalog()
    if name not in cat:
        raise ServiceError("unknown service for the current mode")
    s = cat[name]
    proc = processes.start_service(name, "service", s["node"], s["argv"])
    if proc.status != "running":
        tail = ""
        try:
            tail = open(proc.log_path, errors="replace").read()[-400:]
        except OSError:
            pass
        raise ServiceError("service failed to start: " + tail.strip().replace("\n", " "))
    return proc


def stop_service(name):
    if name not in service_catalog():
        raise ServiceError("unknown service")
    return processes.stop(name)


def save_upload(uploaded) -> str:
    """Store an uploaded file under data/uploads (the only place the client may read from)."""
    if uploaded.size > MAX_UPLOAD:
        raise ServiceError(f"file too large (max {MAX_UPLOAD // 1024 // 1024} MB)")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", uploaded.name)[:60] or "upload.bin"
    path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
    with open(path, "wb") as fh:
        for chunk in uploaded.chunks():
            fh.write(chunk)
    return str(path)


def sample_file() -> str:
    path = settings.DATA_DIR / "sample.txt"
    if not path.exists():
        path.write_text("AegisNet sample file. The quick brown fox jumps over the lazy dog.\n" * 20)
    return str(path)


def run_client(*, src, proto, host, port, message="", file_path=None,
               count=5, timeout=5.0) -> dict:
    """Run communication.client from `src` ('host' or a lab node) and return its JSON result."""
    if src != HOST_SOURCE and src not in netenv.LAB_NODES:
        raise ServiceError("unknown source node")
    if not netenv.lab_ip_allowed(host):
        raise ServiceError("destination must be inside the lab (10.10.0.0/16 or 127.0.0.0/8)")
    if proto not in ("tcp", "udp"):
        raise ServiceError("protocol must be tcp or udp")
    if not 1 <= int(port) <= 65535:
        raise ServiceError("port must be 1-65535")
    run_node = src if netenv.is_live() else "host"
    argv = ["python3", "-m", "communication.client", "--proto", proto, "--host", host, "--port", str(int(port)),
            "--timeout", str(timeout), "--count", str(count)]
    if file_path:
        argv += ["--file", file_path]
    elif message:
        argv += ["--message", message]
    r = netenv.run_in_node(run_node, argv, timeout=float(timeout) * max(1, count if proto == "udp" else 1) + 20)
    try:
        result = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        result = {"ok": False, "status": "error", "steps": [],
                  "error": (r.error or r.stderr.strip() or "client produced no result")[:300]}
    result["ran_in"] = run_node
    result["mode"] = "live" if run_node != "host" else "host"
    return result


def record_session(result, *, src, proto, host, port, kind, filename="") -> TransferSession:
    resp = result.get("response")
    return TransferSession.objects.create(
        proto=proto, src_node=src, dst_host=host, dst_port=port, kind=kind,
        filename=filename, bytes_sent=result.get("bytes_sent", 0), status=result.get("status", "error"),
        ok=bool(result.get("ok")), connect_ms=result.get("connect_ms"), total_ms=result.get("total_ms"),
        response=json.dumps(resp)[:2000] if resp is not None else "", error=(result.get("error") or "")[:300],
        steps=result.get("steps", []), detail={k: result[k] for k in ("datagrams", "sent", "received", "lost", "loss_pct", "integrity_ok", "sha256_sent") if k in result},
        mode=result.get("mode", "host"),
    )
