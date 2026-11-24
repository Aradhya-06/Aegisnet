import re

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import netenv
from core.events import log_event
from core.models import Node

from . import services
from .models import MetricSample

_TARGET = re.compile(r"^[A-Za-z0-9._-]{1,253}$")


def _node_choices():
    return [("host", "Host (this machine)")] + [(n.name, n.label) for n in Node.objects.all()]


def index(request):
    return render(request, "monitoring/index.html", {
        "nodes": _node_choices(), "commands": list(services.COMMANDS),
       # "how": HOW_OBTAINED,
    })


@require_GET
def api_interfaces(request):
    node = request.GET.get("node", "host")
    if node == "host":
        return JsonResponse({"node": "host", "interfaces": services.host_interfaces(), "error": None})
    if node not in netenv.LAB_NODES:
        return JsonResponse({"error": "unknown node"}, status=400)
    return JsonResponse(services.node_interfaces(node))


@require_GET
def api_connections(request):
    return JsonResponse(services.host_connections())


@require_POST
def api_ping(request):
    node = request.POST.get("node", "host")
    target = request.POST.get("target", "").strip()
    try:
        count = max(1, min(int(request.POST.get("count", 4)), 10))
    except ValueError:
        return JsonResponse({"error": "count must be a number"}, status=400)
    if node != "host" and node not in netenv.LAB_NODES:
        return JsonResponse({"error": "unknown node"}, status=400)
    if not netenv.lab_ip_allowed(target):
        return JsonResponse({"error": "target must be an IP inside the lab ranges (10.10.0.0/16 or 127.0.0.0/8)"}, status=400)
    res = services.ping(node, target, count=count, timeout=1)
    log_event("monitoring", f"ping {node}->{target}: " + ("reachable" if res["reachable"] else "unreachable"),
              "info" if res["reachable"] else "warning", loss=res["loss_pct"], rtt=res["rtt_avg"])
    return JsonResponse(res)


@require_POST
def api_command(request):
    name = request.POST.get("command", "")
    node = request.POST.get("node", "host")
    target = request.POST.get("target", "").strip()
    if node != "host" and node not in netenv.LAB_NODES:
        return JsonResponse({"error": "unknown node"}, status=400)
    if target and not _TARGET.match(target):
        return JsonResponse({"error": "invalid target"}, status=400)
    if name == "traceroute" and not netenv.lab_ip_allowed(target):
        return JsonResponse({"error": "traceroute target must be a lab IP"}, status=400)
    return JsonResponse(services.run_command(name, node, target))


@require_POST
def api_probe(request):
    """Ping across every lab link now and update link status."""
    results = services.probe_links()
    return JsonResponse({"mode": netenv.lab_status()["mode"], "links": results})


@require_GET
def api_history(request):
    target = request.GET.get("target", "")
    if not _TARGET.match(target):
        return JsonResponse({"error": "invalid target"}, status=400)
    rows = MetricSample.objects.filter(target=target).order_by("-timestamp")[:60]
    data = [{"t": r.timestamp.isoformat(), "rx": r.rx_rate_bps, "tx": r.tx_rate_bps, "util": r.utilization_pct}
            for r in reversed(list(rows))]
    return JsonResponse({"target": target, "samples": data})


HOW_OBTAINED = {
    "Interfaces, IP, MAC, state": "psutil.net_if_addrs() / net_if_stats() for the host; `ip -j addr` and `ip -j -s link` inside each lab namespace.",
    "Bytes and packets": "Kernel interface counters (psutil.net_io_counters(pernic=True) or `ip -s link`). They only ever increase.",
    "Throughput": "(counter now - counter before) x 8 / seconds between two readings. Needs two readings, so the first one is empty.",
    "Utilisation": "Throughput / link capacity. Host: the speed psutil reports for the NIC (empty if the driver reports none). Lab: the nominal capacity configured for the link (100 Mbit/s) - a configured value, not a measurement.",
    "Connections": "psutil.net_connections(kind='inet') on the host; `ss -Htan state established` in each lab namespace.",
    "Latency and loss": "The ping utility (ICMP echo). Latency = rtt avg from ping's summary line, loss = its 'packet loss' percentage.",
}
