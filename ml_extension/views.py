import json
import shutil

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import processes
from core.events import log_event

from . import collect, features, predict, train

ML_DIR = settings.DATA_DIR / "ml"


def _metrics():
    p = ML_DIR / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else None


def _dataset_info():
    p = collect.dataset_path()
    if not p.exists():
        return None
    try:
        df = train.load_dataset(p)
        return {"rows": int(len(df)), "per_class": {k: int(v) for k, v in df["label"].value_counts().items()}}
    except train.MLError as exc:
        return {"error": str(exc)}


def index(request):
    try:
        train._import()
        libs = True
    except train.MLError:
        libs = False
    return render(request, "ml_extension/index.html", {
        "libs": libs, "dataset": _dataset_info() if libs else None, "metrics_json": json.dumps(_metrics()) if _metrics() else "null",
        "features": features.DESCRIPTIONS, "levels": collect.LEVELS, "shaped": collect.SHAPED_MBIT,
        "collecting": processes.is_running("ml-collector"),
    })


@require_POST
def api_collect(request):
    proc = processes.start_manage_command("ml-collector", "ml", ["collect_ml_data", "--samples", "40"])
    log_event("ml", "dataset collection started (about 3 minutes)", "info")
    return JsonResponse({"running": proc.status == "running", "log": proc.log_path})


@require_POST
def api_upload(request):
    f = request.FILES.get("file")
    if not f or f.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "upload a CSV under 5 MB"}, status=400)
    ML_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ML_DIR / "upload.csv"
    tmp.write_bytes(f.read())
    try:
        df = train.load_dataset(tmp)
    except train.MLError as exc:
        tmp.unlink(missing_ok=True)
        return JsonResponse({"error": str(exc)}, status=400)
    shutil.move(tmp, collect.dataset_path())
    return JsonResponse({"rows": int(len(df))})


@require_POST
def api_train(request):
    try:
        result = train.train(collect.dataset_path(), ML_DIR)
    except (train.MLError, FileNotFoundError) as exc:
        return JsonResponse({"error": str(exc) if not isinstance(exc, FileNotFoundError) else "no dataset yet"}, status=400)
    log_event("ml", f"model trained: accuracy {result['ml']['accuracy']} (threshold baseline {result['threshold_baseline']['accuracy']})", "success")
    return JsonResponse(result)


@require_GET
def api_predict(request):
    from monitoring.models import MetricSample
    from core.models import Link
    link = Link.objects.get(name=collect.LINK)
    samples = list(MetricSample.objects.filter(kind="link", target=link.name, utilization_pct__isnull=False)[:2])
    if not samples:
        return JsonResponse({"error": "no link measurements yet - open the Dashboard with the lab running first"}, status=400)
    s = samples[0]
    pps = 0.0
    if len(samples) == 2 and None not in (s.tx_packets, samples[1].tx_packets):
        dt = (s.timestamp - samples[1].timestamp).total_seconds()
        pps = (s.tx_packets - samples[1].tx_packets) / dt if dt > 0 else 0.0
    rate = max(s.rx_rate_bps or 0, s.tx_rate_bps or 0)
    row = {"utilization_pct": s.utilization_pct, "throughput_mbps": rate / 1e6, "latency_ms": link.last_latency_ms,
           "loss_pct": link.last_loss_pct, "active_connections": s.active_connections or 0, "packets_per_sec": pps}
    try:
        return JsonResponse(predict.predict_row(ML_DIR, row))
    except train.MLError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
