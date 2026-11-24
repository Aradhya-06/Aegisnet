"""Self-healing: find an alternative path, install it in the lab, verify, record.

Steps (matching the project brief):
  1. identify the failed link(s) on the flow's current path
  2. check whether an alternative path exists          } the routing module's
  3. recalculate the route                              } Dijkstra on the lab graph
  4. switch traffic: `ip route replace` inside the lab routers (live), or update the
     model only (simulated) - and the record says which one happened
  5. verify connectivity again (real ping in live mode)
  6. record success/failure and show it on the dashboard

Safety: only routes for lab subnets (10.10.x.0/30) inside aegis_* namespaces are ever
changed; the host routing table is never touched. Dry-run shows the plan only.
Disruptive actions require confirm=True. Rollback = scripts/restore_network.sh
(re-installs the baseline routes) via `restore_all()`.
"""
from __future__ import annotations

import time

from django.utils import timezone

from core import netenv, processes
from core.events import log_event
from core.models import EventLog, Link, Node
from monitoring import services as mon
from routing import link_state
from routing.lab import lab_graph

from .models import Alert, FailureInjection, MonitoredFlow, RecoveryEvent


class RecoveryError(ValueError):
    pass


def link_between(a: str, b: str) -> Link | None:
    return (Link.objects.filter(node_a__name=a, node_b__name=b).first()
            or Link.objects.filter(node_a__name=b, node_b__name=a).first())


def _node_ip_on(link: Link, node_name: str) -> str:
    return link.ip_a if link.node_a.name == node_name else link.ip_b


def plan_route_changes(path: list[str]) -> list[dict]:
    """Per-router `ip route replace` commands so traffic flows src->dst AND back along `path`.

    path = [src, router..., dst]. For router i: route to dst's subnet via the next node,
    and route to src's subnet via the previous node. A router directly attached to a subnet
    needs no route for it.
    """
    if len(path) < 3:
        return []
    src_subnet = link_between(path[0], path[1]).subnet
    dst_subnet = link_between(path[-2], path[-1]).subnet
    plan = []
    for i in range(1, len(path) - 1):
        router = path[i]
        if i < len(path) - 2:                                   # forward direction
            nxt = path[i + 1]
            link = link_between(router, nxt)
            plan.append({"node": router, "dest": dst_subnet, "via": _node_ip_on(link, nxt),
                         "argv": ["ip", "route", "replace", dst_subnet, "via", _node_ip_on(link, nxt)]})
        if i > 1:                                               # reverse direction
            prv = path[i - 1]
            link = link_between(router, prv)
            plan.append({"node": router, "dest": src_subnet, "via": _node_ip_on(link, prv),
                         "argv": ["ip", "route", "replace", src_subnet, "via", _node_ip_on(link, prv)]})
    return plan


def _path_links(path):
    return [link_between(a, b) for a, b in zip(path, path[1:])]


def _link_is_down(link: Link, live: bool) -> bool:
    return link.status == Link.DOWN if live else link.admin_down


def verify(flow: MonitoredFlow, path: list[str], live: bool):
    if live:
        p = mon.ping(flow.src.name, flow.dst.ip_primary, count=3, timeout=1)
        ok = bool(p["reachable"])
        detail = (f"ping {flow.src.name} -> {flow.dst.ip_primary}: {p['received']}/{p['sent']} replies"
                  + (f", avg {p['rtt_avg']} ms" if p["rtt_avg"] is not None else ""))
        return ok, detail, p
    down = [l.name for l in _path_links(path) if l.admin_down]
    return (not down), ("SIMULATED check on the graph model (no packets were sent): " +
                        ("all links on the new path are up" if not down else "links down on path: " + ", ".join(down))), None


def recover_flow(flow: MonitoredFlow, *, dry_run=False, confirm=False, alert: Alert | None = None,
                 trigger="manual") -> RecoveryEvent:
    if not dry_run and not confirm:
        raise RecoveryError("confirmation required: recovery changes routes in the test network")
    status = netenv.lab_status()
    live = status["live"]
    mode = "live" if live else "simulated"
    t0 = time.monotonic()
    old_path = list(flow.current_path or flow.primary_path)
    event = RecoveryEvent(flow=flow, alert=alert, old_path=old_path, mode=mode, dry_run=dry_run, trigger=trigger)

    failed = [l.name for l in _path_links(old_path) if l and _link_is_down(l, live)]
    event.failed_links = failed
    graph = lab_graph()
    sp = link_state.shortest_path(graph, flow.src.name, flow.dst.name)

    def finish(result, message):
        event.result, event.message = result, message
        event.duration_ms = round((time.monotonic() - t0) * 1000, 1)
        event.save()
        level = {"success": EventLog.SUCCESS, "dry_run": EventLog.INFO, "no_change": EventLog.INFO}.get(result, EventLog.ERROR)
        log_event("recovery", f"{flow.name}: {result} - {message}", level, event=event.pk, mode=mode)
        return event

    if not sp["path"]:
        event.new_path = []
        return finish("no_path", "no alternative path exists: " + (f"failed link(s) {', '.join(failed)} disconnect the destination" if failed else "destination unreachable in the topology"))
    event.new_path = sp["path"]
    if not failed and sp["path"] == old_path:
        return finish("no_change", "the current path is healthy and is already the shortest path")

    plan = plan_route_changes(sp["path"])
    event.commands = [{"node": c["node"], "command": "ip route replace %s via %s" % (c["dest"], c["via"]), "ok": None, "output": ""}
                      for c in plan]
    if dry_run:
        return finish("dry_run", "plan only - nothing was changed: " + " -> ".join(sp["path"]))

    if live:
        for cmd, entry in zip(plan, event.commands):
            r = netenv.run_in_node(cmd["node"], cmd["argv"])
            entry["ok"], entry["output"] = r.ok, (r.error or r.stderr or r.stdout).strip()[:200]
            if not r.ok:
                return finish("failed", f"route change failed on {cmd['node']}: {entry['output']} (run scripts/restore_network.sh all to roll back)")
    else:
        for entry in event.commands:
            entry["ok"], entry["output"] = None, "simulated - not executed"

    ok, detail, _ = verify(flow, sp["path"], live)
    event.verified, event.verification = ok, detail
    if ok:
        flow.current_path, flow.status = sp["path"], "up"
        flow.save(update_fields=["current_path", "status"])
        return finish("success", f"traffic moved to {' -> '.join(sp['path'])} and verified" + ("" if live else " (SIMULATED)"))
    return finish("failed", "routes were changed but connectivity could not be verified: " + detail)


# ----------------------------------------------------------------------- failure injection
def inject_link_failure(link_name: str, *, dry_run=False, confirm=False) -> FailureInjection:
    link = Link.objects.filter(name=link_name).first()
    if not link:
        raise RecoveryError("unknown lab link")
    if not dry_run and not confirm:
        raise RecoveryError("confirmation required: this disables a link in the test network")
    live = netenv.is_live()
    rec = FailureInjection(kind="link", target=link.name, dry_run=dry_run, mode="live" if live else "simulated")
    if live:
        r = netenv.run_script("simulate_failure.sh", link.name, *(["--dry-run"] if dry_run else []))
        rec.ok, rec.output = r.ok, (r.text or r.error).strip()
    else:
        rec.ok = True
        rec.output = ("SIMULATED: would mark link %s down in the model" % link.name) if dry_run else \
                     "SIMULATED: link %s marked down in the model (no real interface was touched)" % link.name
    if rec.ok and not dry_run:
        link.admin_down = True
        link.save(update_fields=["admin_down"])
    rec.save()
    log_event("recovery", f"failure injection {'(dry-run) ' if dry_run else ''}on link {link.name}: {'ok' if rec.ok else 'FAILED'}",
              EventLog.WARNING if rec.ok else EventLog.ERROR, mode=rec.mode)
    return rec


def restore_all(*, dry_run=False) -> FailureInjection:
    live = netenv.is_live()
    rec = FailureInjection(kind="restore", target="all", dry_run=dry_run, mode="live" if live else "simulated")
    if live:
        r = netenv.run_script("restore_network.sh", "all", *(["--dry-run"] if dry_run else []))
        rec.ok, rec.output = r.ok, (r.text or r.error).strip()
    else:
        rec.ok, rec.output = True, "SIMULATED: all links marked up and baseline paths restored in the model"
    if rec.ok and not dry_run:
        Link.objects.update(admin_down=False, status=Link.UNKNOWN)
        for f in MonitoredFlow.objects.all():
            f.current_path, f.status = f.primary_path, "unknown"
            f.save(update_fields=["current_path", "status"])
    rec.save()
    log_event("recovery", f"rollback / restore {'(dry-run) ' if dry_run else ''}: {'ok' if rec.ok else 'FAILED'}",
              EventLog.SUCCESS if rec.ok else EventLog.ERROR, mode=rec.mode)
    return rec


def inject_service_failure(name: str) -> FailureInjection:
    ok = processes.crash(name)
    rec = FailureInjection.objects.create(kind="service", target=name, mode="live" if netenv.is_live() else "simulated", ok=ok,
                                          output="process killed" if ok else "service was not running")
    log_event("recovery", f"service failure injected: {name} ({'killed' if ok else 'not running'})",
              EventLog.WARNING if ok else EventLog.INFO)
    return rec
