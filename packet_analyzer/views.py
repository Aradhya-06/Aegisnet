import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from core import netenv
from core.events import log_event
from core.models import Node

from . import capture, parser
from .models import PacketCapture, PacketRecord


def index(request):
    return render(request, "packet_analyzer/index.html", {
        "nodes": [("host", "Host (loopback only)")] + [(n.name, n.label) for n in Node.objects.all()],
        "captures": PacketCapture.objects.all()[:15],
        "traffic_types": capture.TRAFFIC_TYPES,
    })


@require_POST
def api_capture(request):
    p = request.POST
    try:
        cap = capture.run_capture(
            p.get("node", "host"), p.get("interface", "").strip(), int(p.get("duration", 8)),
            p.get("bpf", "").strip(), int(p.get("snaplen", 512)), p.getlist("traffic"))
    except (capture.CaptureError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    log_event("packet_analyzer", f"capture #{cap.pk} on {cap.node}:{cap.interface} -> {cap.packet_count} packets ({cap.status})",
              "success" if cap.status == "done" else "error", capture=cap.pk)
    return JsonResponse({"id": cap.pk, "status": cap.status, "packets": cap.packet_count, "error": cap.error,
                         "traffic": cap.traffic})


def detail(request, pk):
    cap = get_object_or_404(PacketCapture, pk=pk)
    proto = request.GET.get("proto", "all")
    q = request.GET.get("q", "").strip()
    packets = cap.packets.all()
    if proto in ("dns", "http", "tls"):
        packets = packets.filter(app=proto)
    elif proto in ("tcp", "udp", "icmp", "arp"):
        packets = packets.filter(proto=proto.upper())
    elif proto == "other":
        packets = packets.exclude(proto__in=["TCP", "UDP", "ICMP", "ARP"])
    if q:
        cond = Q(src_ip__icontains=q) | Q(dst_ip__icontains=q) | Q(info__icontains=q)
        if q.isdigit():
            cond |= Q(sport=int(q)) | Q(dport=int(q))
        packets = packets.filter(cond)
    page = Paginator(packets, 100).get_page(request.GET.get("page"))
    all_rows = cap.packets.values_list("proto", "app")
    counts = {}
    for pr, app in all_rows:
        counts[pr] = counts.get(pr, 0) + 1
        if app:
            counts[app.upper()] = counts.get(app.upper(), 0) + 1
    first = cap.packets.first()
    t0 = first.ts if first else 0
    for pk_ in page:
        pk_.ts = round(pk_.ts - t0, 6)
    return render(request, "packet_analyzer/detail.html", {
        "cap": cap, "page": page, "proto": proto, "q": q, "filters": parser.PROTOCOL_FILTERS,
        "counts_json": json.dumps(counts), "t0": t0, "tshark": bool(shutil.which("tshark")),
    })


def _pcap_file(cap: PacketCapture) -> Path:
    path = Path(cap.pcap_path).resolve()
    if (settings.DATA_DIR / "pcaps").resolve() not in path.parents or not path.is_file():
        raise Http404("capture file not available")
    return path


@require_GET
def download(request, pk):
    cap = get_object_or_404(PacketCapture, pk=pk)
    path = _pcap_file(cap)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name, content_type="application/vnd.tcpdump.pcap")


@require_GET
def tshark(request, pk):
    """Independent decode with TShark (the command-line Wireshark) as a cross-check of Scapy."""
    cap = get_object_or_404(PacketCapture, pk=pk)
    path = _pcap_file(cap)
    exe = shutil.which("tshark")
    if not exe:
        return JsonResponse({"ok": False, "output": "tshark is not installed (sudo apt install tshark)"})
    cmd = [exe, "-r", str(path), "-c", "40", "-d", "udp.port==5353,dns", "-T", "fields", "-E", "separator=|",
           "-e", "frame.number", "-e", "ip.src", "-e", "ip.dst", "-e", "_ws.col.Protocol", "-e", "frame.len", "-e", "_ws.col.Info"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return JsonResponse({"ok": False, "output": "tshark timed out"})
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return JsonResponse({"ok": r.returncode == 0, "output": "\n".join(lines) or r.stderr[-300:]})


@require_GET
def api_interfaces(request):
    node = request.GET.get("node", "host")
    if node == "host":
        return JsonResponse({"interfaces": ["lo"]})
    if node not in netenv.LAB_NODES:
        return JsonResponse({"error": "unknown node"}, status=400)
    from monitoring.services import node_interfaces
    res = node_interfaces(node)
    return JsonResponse({"interfaces": [i["name"] for i in res["interfaces"]], "error": res.get("error")})
