from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core.events import log_event

from . import ns2_runner
from .models import SimulationRun


def index(request):
    return render(request, "simulation/index.html", {
        "scenarios": ns2_runner.SCENARIOS, "ns_path": ns2_runner.ns_binary(),
        "runs": SimulationRun.objects.all()[:15],
    })


@require_POST
def api_run(request):
    key = request.POST.get("scenario", "")
    if key not in ns2_runner.SCENARIOS:
        return JsonResponse({"error": "unknown scenario"}, status=400)
    run = ns2_runner.run_scenario(key)
    log_event("simulation", f"NS2 scenario '{key}': {run.status}",
              "success" if run.executed else "warning", run=run.pk)
    return JsonResponse({"id": run.pk, "status": run.status, "executed": run.executed, "log": run.log_tail[-300:]})


def _summary(run):
    if not run:
        return None
    flows = run.metrics.get("flows", {})
    head = flows.get("1", {})
    return {"id": run.pk, "created": run.created.strftime("%Y-%m-%d %H:%M"), "duration_s": run.duration_s,
            "headline": head, "flows": list(flows.values())}


@require_GET
def api_compare(request):
    """Latest executed run of each scenario, for side by side comparison (all values SIMULATED)."""
    data = {}
    for key, run in ns2_runner.latest_by_scenario().items():
        info = _summary(run)
        data[key] = {"title": ns2_runner.SCENARIOS[key]["title"], "run": info,
                     "series": (run.metrics["flows"].get("1", {}).get("series", []) if run else [])}
    return JsonResponse({"simulated": True, "scenarios": data})


@require_GET
def api_run_detail(request, pk):
    run = SimulationRun.objects.filter(pk=pk).first()
    if not run:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"id": run.pk, "scenario": run.scenario, "status": run.status, "executed": run.executed,
                         "log": run.log_tail, "metrics": run.metrics})


@require_GET
def api_script(request):
    key = request.GET.get("scenario", "")
    if key not in ns2_runner.SCENARIOS:
        return JsonResponse({"error": "unknown scenario"}, status=400)
    return JsonResponse({"scenario": key, "tcl": ns2_runner.script_text(key)})
