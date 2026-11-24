import time

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from monitoring import services as mon
from recovery.models import Alert, MonitoredFlow, RecoveryEvent

from . import netenv
from .models import EventLog, Link


def dashboard(request):
    return render(request, "core/dashboard.html", {"links": Link.objects.select_related("node_a", "node_b")})


def about(request):
    return render(request, "core/about.html", {"co_map": CO_MAP})


@require_GET
def api_dashboard(request):
    """Everything on the dashboard, measured now. Counters are real; nothing is generated."""
    snap = mon.collect_snapshot(store=True)
    links = list(Link.objects.select_related("node_a", "node_b"))
    live = netenv.lab_status()
    up = [l for l in links if l.status in (Link.UP, Link.DEGRADED)]
    lat = [l.last_latency_ms for l in up if l.last_latency_ms is not None]
    loss = [l.last_loss_pct for l in up if l.last_loss_pct is not None]
    util = [c["utilization_pct"] for c in snap["lab"] if c.get("utilization_pct") is not None]
    lab_rate = sum((c.get("rx_rate_bps") or 0) + (c.get("tx_rate_bps") or 0) for c in snap["lab"])
    flows = MonitoredFlow.objects.all()
    if any(l.status == Link.DOWN for l in links) or any(f.status == "down" for f in flows):
        overall = "degraded"
    elif any(l.status == Link.DEGRADED for l in links):
        overall = "warning"
    elif all(l.status == Link.UNKNOWN for l in links):
        overall = "unknown"
    else:
        overall = "healthy"
    return JsonResponse({
        "t": snap["time"], "mode": live["mode"], "reason": live["reason"], "overall": overall,
        "interfaces": snap["host"]["interfaces"], "interfaces_up": snap["host"]["interfaces_up"],
        "connections_host": snap["host"]["connections"], "connections_lab": snap["lab_connections"],
        "host_rx_bytes": snap["host"]["rx_bytes"], "host_tx_bytes": snap["host"]["tx_bytes"],
        "lab_rx_bytes": sum(c.get("rx_bytes") or 0 for c in snap["lab"]) if snap["lab"] else None,
        "lab_tx_bytes": sum(c.get("tx_bytes") or 0 for c in snap["lab"]) if snap["lab"] else None,
        "lab_rate_bps": lab_rate if snap["lab"] else None,
        "host_rate_bps": snap["host"]["rx_rate_bps"] + snap["host"]["tx_rate_bps"],
        "utilization_pct": round(max(util), 2) if util else None,
        "latency_ms": round(sum(lat) / len(lat), 3) if lat else None,
        "loss_pct": round(sum(loss) / len(loss), 2) if loss else None,
        "links": [{"name": l.name, "status": l.status, "latency": l.last_latency_ms, "loss": l.last_loss_pct} for l in links],
        "alerts": [{"time": a.created.strftime("%H:%M:%S"), "severity": a.severity, "kind": a.get_kind_display(),
                    "target": a.target, "reason": a.reason, "resolved": a.resolved}
                   for a in Alert.objects.all()[:6]],
        "recoveries": [{"time": e.created.strftime("%H:%M:%S"), "flow": e.flow.name, "result": e.result, "mode": e.mode,
                        "path": " > ".join(e.new_path), "message": e.message, "dry_run": e.dry_run}
                       for e in RecoveryEvent.objects.select_related("flow")[:5]],
        "timeline": [{"time": ev.timestamp.strftime("%H:%M:%S"), "source": ev.source, "level": ev.level, "message": ev.message}
                     for ev in EventLog.objects.all()[:12]],
    })


@require_POST
def api_probe_all(request):
    """Run a link probe round (ping across every link) from the dashboard."""
    t0 = time.monotonic()
    res = mon.probe_links()
    return JsonResponse({"links": res, "ms": round((time.monotonic() - t0) * 1000)})


# Course-outcome mapping shown on the documentation page: every row names a feature that runs.
CO_MAP = [
    ("CO1", "Wired technologies, interfaces, addressing, Linux tools, TCP/IP",
     "Network Monitoring page; isolated namespace lab (scripts/setup_network.sh)",
     "Interfaces, IP/MAC, counters, ip/ss/ping/traceroute output for host and lab nodes; 6-node topology with /30 links"),
    ("CO2", "TCP/UDP socket programming",
     "TCP / UDP page (communication/)",
     "Separate TCP and UDP client/server programs running inside lab nodes, with timed life-cycle steps (handshake, data, FIN), file transfer with a checksum and UDP loss/RTT measurement"),
    ("CO3", "Routing algorithms and NS2 performance evaluation",
     "Routing Visualizer, NS2 Simulation page (routing/, simulation/)",
     "Distance Vector and Dijkstra on an editable graph; 4 NS2 scenarios with throughput, delay, PDR and loss parsed from real trace files"),
    ("CO4", "Packet visualisation and analysis (HTTP, DNS, TCP, UDP, IP, TLS)",
     "Packet Analyzer page (packet_analyzer/)",
     "tcpdump capture in the lab, Scapy decoding of Ethernet/IP/TCP/UDP/ICMP/DNS/HTTP/TLS handshakes, filters, PCAP download for Wireshark, TShark cross-check"),
    ("CO5", "Real-world application: automated fault detection and recovery",
     "Fault & Recovery page (recovery/)",
     "Detector finds a failed link, the recovery engine installs a backup route in the lab routers, verifies it with a real ping and can roll back; lab-only safety rules (dry-run, confirmation, allow-listed helper)"),
]
