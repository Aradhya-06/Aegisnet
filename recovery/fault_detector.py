"""Fault detection from REAL measurements of the lab (conventional threshold logic, no AI).

One detection cycle:
  1. ping across every link          -> link status, latency, loss         (live)
  2. read interface state            -> interface down vs. link failure     (live)
  3. ping every monitored flow       -> end-to-end reachability            (live)
  4. connect() to expected TCP services
  5. compare against the configured thresholds, open / resolve alerts
  6. optionally hand broken flows to the recovery engine

In SIMULATED mode (no namespaces / no sudo) failures come from the injected-failure flag
on the model and no latency/loss numbers are produced - alerts are marked "simulated".
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from django.utils import timezone

from core import netenv
from core.events import log_event
from core.models import EventLog, Link, ManagedProcess, Node
from monitoring import services as mon

from . import recovery_engine
from .models import Alert, MonitoredFlow, RecoveryEvent, ThresholdConfig


def thresholds() -> dict[str, float]:
    return {t.key: t.value for t in ThresholdConfig.objects.filter(enabled=True)}


def _iface_down(node: str, iface: str):
    """True if the interface is administratively/operationally down (None when unknown)."""
    r = netenv.run_in_node(node, ["ip", "-j", "link", "show", "dev", iface])
    try:
        info = json.loads(r.stdout)[0]
    except (ValueError, IndexError):
        return None
    return "UP" not in info.get("flags", []) or info.get("operstate") == "DOWN"


def run_cycle(auto_recover=False, dry_run=False) -> dict:
    status = netenv.lab_status(force=True)
    live, mode = status["live"], status["mode"]
    th = thresholds()
    found: dict[tuple, dict] = {}

    def detect(kind, target, severity, reason, action, link=None, flow=None):
        found[(kind, target)] = dict(severity=severity, reason=reason, action=action, link=link, flow=flow)

    # 1 + 2: links
    mon.probe_links(count=2)
    links = list(Link.objects.select_related("node_a", "node_b"))
    for l in links:
        if l.status == Link.DOWN:
            why = ("no ICMP reply across the link" if live else "failure injected in the simulation")
            detect("link_down", l.name, "critical", f"Link {l.name} ({l.node_a.label} - {l.node_b.label}): {why}",
                   "Recovery engine will look for an alternative path; repair with scripts/restore_network.sh " + l.name, link=l)
            if live:
                downs = []
                for end, iface in ((l.node_a, l.if_a), (l.node_b, l.if_b)):
                    if _iface_down(end.name, iface):
                        downs.append(f"{iface} on {end.label}")
                if downs:
                    detect("interface_down", l.name, "critical", "Interface DOWN: " + ", ".join(downs),
                           "Bring the interface up (ip link set <if> up) or restore the link", link=l)
        elif live and l.status in (Link.UP, Link.DEGRADED):
            if "latency_ms" in th and l.last_latency_ms is not None and l.last_latency_ms > th["latency_ms"]:
                detect("high_latency", l.name, "warning", f"Latency {l.last_latency_ms:.2f} ms exceeds threshold {th['latency_ms']:.0f} ms on {l.name}",
                       "Check queueing / impairments on the link", link=l)
            if "loss_pct" in th and l.last_loss_pct is not None and l.last_loss_pct > th["loss_pct"]:
                detect("packet_loss", l.name, "warning", f"Packet loss {l.last_loss_pct:.0f}% exceeds threshold {th['loss_pct']:.0f}% on {l.name}",
                       "Check the link for errors or impairment (tc netem)", link=l)

    # utilisation (needs two counter readings, so the very first cycle has none)
    if live and "utilization_pct" in th:
        for c in mon.lab_link_counters():
            if c.get("utilization_pct") is not None and c["utilization_pct"] > th["utilization_pct"]:
                l = next(x for x in links if x.name == c["link"])
                detect("high_utilization", l.name, "warning",
                       f"Utilisation {c['utilization_pct']:.1f}% of {l.capacity_mbps} Mbit/s exceeds {th['utilization_pct']:.0f}% on {l.name}",
                       "Shift traffic to another path or raise capacity", link=l)

    # nodes: every link down => unreachable
    for n in Node.objects.all():
        mine = [l for l in links if n.pk in (l.node_a_id, l.node_b_id)]
        if mine and all(l.status == Link.DOWN for l in mine):
            detect("node_unreachable", n.name, "critical", f"{n.label} is unreachable: all {len(mine)} of its link(s) are down",
                   "Restore a link to this node (it has no alternative path if it only has one link)")

    # 3: flows
    flows = list(MonitoredFlow.objects.select_related("src", "dst").filter(enabled=True))

    def check_flow(f):
        if live:
            return f, mon.ping(f.src.name, f.dst.ip_primary, count=3, timeout=1)
        broken = [l.name for l in recovery_engine._path_links(f.current_path or f.primary_path) if l.admin_down]
        return f, {"reachable": not broken, "rtt_avg": None, "loss_pct": None, "broken": broken, "error": ""}

    with ThreadPoolExecutor(max_workers=4) as pool:
        flow_results = list(pool.map(check_flow, flows))
    broken_flows = []
    for f, res in flow_results:
        f.status = "up" if res["reachable"] else "down"
        f.last_latency_ms, f.last_loss_pct, f.last_checked = res.get("rtt_avg"), res.get("loss_pct"), timezone.now()
        f.save(update_fields=["status", "last_latency_ms", "last_loss_pct", "last_checked"])
        if not res["reachable"]:
            broken_flows.append(f)
            via = (" (broken link: " + ", ".join(res["broken"]) + ")") if res.get("broken") else ""
            detect("flow_unreachable", f.name, "critical",
                   f"End-to-end path {f.name} ({' -> '.join(f.current_path)}) is not working{via}",
                   "Recovery engine will recompute the route", flow=f)

    # 4: TCP services that SHOULD be running
    if live:
        from communication.services import service_catalog
        cat = service_catalog()
        for proc in ManagedProcess.objects.filter(kind="service", expected_up=True):
            s = cat.get(proc.name)
            if s and s["proto"] == "tcp":
                src = "a" if s["node"] != "a" else "b"
                pr = mon.tcp_probe(src, s["host"], s["port"])
                if not pr.get("ok"):
                    detect("service_down", proc.name, "critical",
                           f"TCP service {proc.name} ({s['host']}:{s['port']}) is not reachable from {src.upper()}: {pr.get('error') or 'connect failed'} "
                           "(the service may be down, or the path to it is broken)",
                           "Restart the service from the Communication page")

    # 5: open new alerts / resolve cleared ones
    open_alerts = {(a.kind, a.target): a for a in Alert.objects.filter(resolved=False)}
    new = []
    for key, d in found.items():
        if key not in open_alerts:
            a = Alert.objects.create(kind=key[0], target=key[1], severity=d["severity"], reason=d["reason"][:300],
                                     suggested_action=d["action"][:300], mode=mode, link=d["link"], flow=d["flow"])
            open_alerts[key] = a
            new.append(a)
            log_event("detector", f"ALERT {key[0]}: {d['reason']}", EventLog.ERROR if d["severity"] == "critical" else EventLog.WARNING,
                      alert=a.pk, mode=mode)
    resolved = []
    for key, a in list(open_alerts.items()):
        if key not in found:
            a.resolved, a.resolved_at = True, timezone.now()
            a.save(update_fields=["resolved", "resolved_at"])
            resolved.append(a)
            log_event("detector", f"resolved {key[0]} on {key[1]}", EventLog.SUCCESS, alert=a.pk)

    # 6: recovery
    recoveries = []
    if auto_recover:
        for f in broken_flows:
            recent = RecoveryEvent.objects.filter(flow=f, dry_run=False, created__gte=timezone.now() - timezone.timedelta(seconds=20)).exists()
            if recent:
                continue
            alert = open_alerts.get(("flow_unreachable", f.name))
            recoveries.append(recovery_engine.recover_flow(f, dry_run=dry_run, confirm=True, alert=alert, trigger="auto"))

    return {"mode": mode, "live": live, "new_alerts": [a.pk for a in new], "resolved": [a.pk for a in resolved],
            "open": len(open_alerts) - len(resolved), "broken_flows": [f.name for f in broken_flows],
            "recoveries": [r.pk for r in recoveries]}
