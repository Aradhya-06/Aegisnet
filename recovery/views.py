from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import netenv, processes
from core.events import log_event
from core.models import Link, ManagedProcess

from . import fault_detector, recovery_engine
from .models import Alert, FailureInjection, MonitoredFlow, RecoveryEvent, ThresholdConfig

DETECTOR = "fault-detector"


def index(request):
    return render(request, "recovery/index.html", {"thresholds": ThresholdConfig.objects.all()})


def _alert(a):
    return {"id": a.pk, "created": a.created.strftime("%H:%M:%S"), "kind": a.get_kind_display(), "severity": a.severity,
            "target": a.target, "reason": a.reason, "action": a.suggested_action, "resolved": a.resolved,
            "resolved_at": a.resolved_at.strftime("%H:%M:%S") if a.resolved_at else None, "mode": a.mode}


def _event(e):
    return {"id": e.pk, "created": e.created.strftime("%H:%M:%S"), "flow": e.flow.name, "failed": e.failed_links,
            "old": e.old_path, "new": e.new_path, "commands": e.commands, "mode": e.mode, "dry_run": e.dry_run,
            "result": e.result, "verified": e.verified, "verification": e.verification, "message": e.message,
            "ms": e.duration_ms, "trigger": e.trigger}


def state_payload():
    status = netenv.lab_status()
    det = ManagedProcess.objects.filter(name=DETECTOR).first()
    if det:
        processes.refresh(det)
    return {
        "lab": status,
        "links": [{"name": l.name, "a": l.node_a.label, "b": l.node_b.label, "status": l.status, "admin_down": l.admin_down,
                   "latency": l.last_latency_ms, "loss": l.last_loss_pct, "cost": l.cost} for l in Link.objects.select_related("node_a", "node_b")],
        "flows": [{"id": f.pk, "name": f.name, "status": f.status, "path": f.current_path, "primary": f.primary_path,
                   "latency": f.last_latency_ms, "loss": f.last_loss_pct} for f in MonitoredFlow.objects.all()],
        "alerts": [_alert(a) for a in Alert.objects.all()[:15]],
        "open_alerts": Alert.objects.filter(resolved=False).count(),
        "recoveries": [_event(e) for e in RecoveryEvent.objects.select_related("flow")[:10]],
        "injections": [{"created": i.created.strftime("%H:%M:%S"), "kind": i.kind, "target": i.target, "dry_run": i.dry_run,
                        "mode": i.mode, "ok": i.ok} for i in FailureInjection.objects.all()[:6]],
        "detector": {"running": bool(det and det.status == "running"), "command": det.command if det else ""},
        "services": [{"name": p.name, "running": p.status == "running", "expected": p.expected_up}
                     for p in ManagedProcess.objects.filter(kind="service")],
    }


@require_GET
def api_state(request):
    return JsonResponse(state_payload())


def _flag(request, name):
    return request.POST.get(name) in ("1", "true", "on")


@require_POST
def api_inject(request):
    try:
        rec = recovery_engine.inject_link_failure(request.POST.get("link", ""), dry_run=_flag(request, "dry_run"),
                                                  confirm=_flag(request, "confirm"))
    except recovery_engine.RecoveryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": rec.ok, "output": rec.output, "mode": rec.mode, "dry_run": rec.dry_run})


@require_POST
def api_restore(request):
    rec = recovery_engine.restore_all(dry_run=_flag(request, "dry_run"))
    return JsonResponse({"ok": rec.ok, "output": rec.output, "mode": rec.mode})


@require_POST
def api_detect(request):
    summary = fault_detector.run_cycle(auto_recover=_flag(request, "auto_recover"), dry_run=_flag(request, "dry_run"))
    return JsonResponse(summary)


@require_POST
def api_recover(request):
    flow = MonitoredFlow.objects.filter(pk=request.POST.get("flow") or 0).first()
    if not flow:
        return JsonResponse({"error": "unknown flow"}, status=400)
    try:
        ev = recovery_engine.recover_flow(flow, dry_run=_flag(request, "dry_run"), confirm=_flag(request, "confirm"))
    except recovery_engine.RecoveryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"event": _event(ev)})


@require_POST
def api_detector(request):
    action = request.POST.get("action")
    if action == "start":
        args = ["run_detector", "--interval", "4"]
        if _flag(request, "auto_recover"):
            args.append("--auto-recover")
        proc = processes.start_manage_command(DETECTOR, "detector", args)
        if proc.status != "running":
            return JsonResponse({"error": "detector failed to start - see data/run/fault-detector.log"}, status=500)
        log_event("detector", "background detector started" + (" with auto-recovery" if _flag(request, "auto_recover") else ""), "info")
    elif action == "stop":
        processes.stop(DETECTOR)
        log_event("detector", "background detector stopped", "info")
    else:
        return JsonResponse({"error": "action must be start or stop"}, status=400)
    return JsonResponse(state_payload()["detector"])


@require_POST
def api_service_failure(request):
    name, action = request.POST.get("name", ""), request.POST.get("action", "")
    from communication import services
    try:
        if action == "inject":
            rec = recovery_engine.inject_service_failure(name)
            return JsonResponse({"ok": rec.ok, "output": rec.output})
        if action == "restore":
            services.start_service(name)
            return JsonResponse({"ok": True, "output": "service restarted"})
    except services.ServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"error": "action must be inject or restore"}, status=400)


@require_POST
def api_threshold(request):
    t = ThresholdConfig.objects.filter(key=request.POST.get("key", "")).first()
    if not t:
        return JsonResponse({"error": "unknown threshold"}, status=400)
    try:
        value = float(request.POST.get("value", ""))
    except ValueError:
        return JsonResponse({"error": "value must be a number"}, status=400)
    if not 0 < value <= 100000:
        return JsonResponse({"error": "value out of range"}, status=400)
    t.value = value
    t.enabled = request.POST.get("enabled", "1") in ("1", "true", "on")
    t.save()
    return JsonResponse({"key": t.key, "value": t.value, "enabled": t.enabled})
