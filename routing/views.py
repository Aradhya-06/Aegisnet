import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import netenv
from core.models import Link, Node

from . import distance_vector, link_state
from .lab import lab_graph
from .models import SandboxTopology
from .topology import Graph, TopologyError


def index(request):
    return render(request, "routing/index.html", {
        "saved": SandboxTopology.objects.all(),
        "nodes": [(n.name, n.label) for n in Node.objects.all()],
    })


@require_GET
def api_lab(request):
    """Lab topology as JSON for the visualiser (read-only copy, a sandbox is created from it)."""
    return JsonResponse({"graph": lab_graph().to_json(), "mode": netenv.lab_status()["mode"]})


@require_POST
def api_run(request):
    try:
        body = json.loads(request.body)
        graph = Graph.from_json(body["graph"])
        src, dst = body["source"], body["dest"]
        algo = body.get("algorithm", "link_state")
        if algo == "link_state":
            result = link_state.run_link_state(graph, src, dst)
        elif algo == "distance_vector":
            prev = Graph.from_json(body["previous_graph"]) if body.get("previous_graph") else None
            result = distance_vector.run_distance_vector(graph, src, dst, bool(body.get("split_horizon", True)), prev)
        else:
            return JsonResponse({"error": "algorithm must be link_state or distance_vector"}, status=400)
    except (TopologyError, KeyError, ValueError, TypeError) as exc:
        return JsonResponse({"error": f"invalid request: {exc}"}, status=400)
    result["note"] = "Computed on the Python graph model. No Linux route was changed."
    return JsonResponse(result)


@require_POST
def api_save(request):
    try:
        body = json.loads(request.body)
        name = str(body["name"]).strip()[:60]
        Graph.from_json(body["graph"])           # validate
    except (TopologyError, KeyError, ValueError, TypeError) as exc:
        return JsonResponse({"error": f"invalid topology: {exc}"}, status=400)
    if not name:
        return JsonResponse({"error": "name required"}, status=400)
    SandboxTopology.objects.update_or_create(name=name, defaults={"data": body["graph"]})
    return JsonResponse({"saved": name})


@require_GET
def api_saved(request):
    name = request.GET.get("name", "")
    t = SandboxTopology.objects.filter(name=name).first()
    if not t:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"graph": t.data})


@require_GET
def api_kernel_routes(request):
    """The REAL Linux routing table of a lab node (to contrast with the algorithm's paper result)."""
    node = request.GET.get("node", "r1")
    if node not in netenv.LAB_NODES:
        return JsonResponse({"error": "unknown node"}, status=400)
    if not netenv.is_live():
        return JsonResponse({"live": False, "output": "", "reason": netenv.lab_status()["reason"]})
    r = netenv.run_in_node(node, ["ip", "route", "show"])
    return JsonResponse({"live": True, "node": node, "output": r.text.strip(), "error": r.error})
