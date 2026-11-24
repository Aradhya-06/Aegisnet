import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import netenv
from core.events import log_event
from core.models import Node

from . import services
from .models import TransferSession


def _sources():
    return [("host", "Host (this machine)")] + [(n.name, n.label) for n in Node.objects.filter(kind="host")]


def index(request):
    return render(request, "communication/index.html", {
        "sources": _sources(),
        "services": services.services_status(),
        "history": TransferSession.objects.all()[:12],
        "default_dst": json.dumps({n.name: n.ip_primary for n in Node.objects.filter(kind="host")}),
    })


@require_GET
def api_services(request):
    return JsonResponse({"services": services.services_status()})


@require_POST
def api_service_action(request):
    name, action = request.POST.get("name", ""), request.POST.get("action", "")
    try:
        if action == "start":
            services.start_service(name)
            log_event("communication", f"started service {name}", "success")
        elif action == "stop":
            services.stop_service(name)
            log_event("communication", f"stopped service {name}", "warning")
        else:
            return JsonResponse({"error": "action must be start or stop"}, status=400)
    except services.ServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"services": services.services_status()})


def _int(value, lo, hi, default):
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


@require_POST
def api_send(request):
    p = request.POST
    proto, src, host = p.get("proto", "tcp"), p.get("src", "host"), p.get("host", "").strip()
    port = _int(p.get("port"), 1, 65535, 0)
    count = _int(p.get("count"), 1, 50, 5)
    timeout = _int(p.get("timeout"), 1, 10, 3)
    message = p.get("message", "")[:10000]
    use_sample = p.get("use_sample") == "1"
    kind, filename, file_path = "message", "", None
    try:
        upload = request.FILES.get("file")
        if upload:
            file_path, kind, filename = services.save_upload(upload), "file", upload.name
        elif use_sample:
            file_path, kind, filename = services.sample_file(), "file", "sample.txt"
        elif not message:
            message = "hello from AegisNet"
        if proto == "udp" and file_path:
            return JsonResponse({"error": "file transmission uses TCP (UDP datagrams are not reliable)"}, status=400)
        result = services.run_client(src=src, proto=proto, host=host, port=port, message=message,
                                     file_path=file_path, count=count, timeout=timeout)
    except services.ServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    sess = services.record_session(result, src=src, proto=proto, host=host, port=port, kind=kind, filename=filename)
    log_event("communication", f"{proto.upper()} {src}->{host}:{port} {kind}: {result.get('status')}",
              "success" if result.get("ok") else "warning", session=sess.pk)
    return JsonResponse({"id": sess.pk, "result": result})


@require_POST
def api_compare(request):
    """Run the same exchange over TCP and UDP so the behaviour can be compared."""
    src, host = request.POST.get("src", "host"), request.POST.get("host", "").strip()
    tcp_port = _int(request.POST.get("tcp_port"), 1, 65535, 9001)
    udp_port = _int(request.POST.get("udp_port"), 1, 65535, 9002)
    try:
        tcp = services.run_client(src=src, proto="tcp", host=host, port=tcp_port, message="compare", timeout=3)
        udp = services.run_client(src=src, proto="udp", host=host, port=udp_port, message="compare", count=10, timeout=1)
    except services.ServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    services.record_session(tcp, src=src, proto="tcp", host=host, port=tcp_port, kind="message")
    services.record_session(udp, src=src, proto="udp", host=host, port=udp_port, kind="message")
    return JsonResponse({"tcp": tcp, "udp": udp})


@require_GET
def api_history(request):
    rows = [{"id": s.pk, "created": s.created.strftime("%H:%M:%S"), "proto": s.proto,
             "src": s.src_node, "dst": f"{s.dst_host}:{s.dst_port}", "kind": s.kind, "status": s.status,
             "ok": s.ok, "connect_ms": s.connect_ms, "total_ms": s.total_ms} for s in TransferSession.objects.all()[:12]]
    return JsonResponse({"history": rows})
