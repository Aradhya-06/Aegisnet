"""Real network measurements. How each metric is obtained (shown in the UI too):

  interfaces / IP / MAC / state   psutil.net_if_addrs(), net_if_stats()   (host)
                                  `ip -j addr`, `ip -j -s link`           (lab nodes)
  bytes & packets                 kernel counters: psutil.net_io_counters(pernic) / `ip -s link`
  throughput (bit/s)              difference of two counter readings / elapsed time
  utilisation %                   throughput / link capacity (host: psutil speed when the NIC
                                  reports one; lab: the configured nominal capacity of the link)
  connections                     psutil.net_connections(kind='inet')  /  `ss -tan` in a namespace
  latency, packet loss            the `ping` utility (ICMP echo); min/avg/max from its summary line
  TCP service reachability        a real connect() (communication.probe)
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psutil
from django.utils import timezone

from core import netenv
from core.models import Link, Node

_PING_LOSS = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received.*?([\d.]+)% packet loss")
_PING_RTT = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")

_last = {}
_last_lock = threading.Lock()

# command name -> (argv template, needs target)
COMMANDS = {
    "ip addr": (["ip", "addr", "show"], False),
    "ip link": (["ip", "-s", "link", "show"], False),
    "ip route": (["ip", "route", "show"], False),
    "ip neigh": (["ip", "neigh", "show"], False),
    "ss -tan": (["ss", "-tan"], False),
    "ss -ulpn": (["ss", "-ulpn"], False),
    "netstat -tan": (["netstat", "-tan"], False),
    "ifconfig": (["ifconfig"], False),
    "traceroute": (["traceroute", "-n", "-m", "8", "-w", "1", "-q", "1"], True),
    "nslookup": (["nslookup"], True),
}


# --------------------------------------------------------------------- ping
def parse_ping(text: str) -> dict:
    out = {"sent": None, "received": None, "loss_pct": None, "rtt_min": None, "rtt_avg": None,
           "rtt_max": None, "rtt_mdev": None}
    m = _PING_LOSS.search(text)
    if m:
        out.update(sent=int(m.group(1)), received=int(m.group(2)), loss_pct=float(m.group(3)))
    m = _PING_RTT.search(text)
    if m:
        out.update(rtt_min=float(m.group(1)), rtt_avg=float(m.group(2)), rtt_max=float(m.group(3)), rtt_mdev=float(m.group(4)))
    return out


def ping(node, host, count=3, timeout=1) -> dict:
    """ICMP echo from `node` ('host' or lab node) to `host`. Returns measured values only."""
    argv = ["ping", "-n", "-c", str(count), "-W", str(timeout), "-i", "0.2", "-w", str(count * timeout + 2), host]
    r = netenv.run_in_node(node, argv, timeout=count * timeout + 6)
    data = parse_ping(r.stdout)
    data.update(host=host, node=node or "host", raw=r.text.strip(), error=r.error)
    if r.returncode == 126 or (r.returncode == 127):
        data["error"] = data["error"] or r.stderr.strip() or "ping could not be run"
    data["reachable"] = bool(data["received"])
    # ping itself ran (exit 1/2, no helper/privilege error) and the kernel said there is no route:
    # that is a MEASURED failure ("unreachable"), not missing data.
    msg = (r.stderr or "").lower()
    data["unreachable"] = bool(not r.error and r.returncode in (1, 2) and
                               ("unreachable" in msg or "no route" in msg))
    if data["sent"] is None and not data["error"]:
        data["error"] = (r.stderr or r.stdout).strip()[:200] or "no ping output"
    return data


def tcp_probe(node, host, port, timeout=1.0) -> dict:
    r = netenv.run_in_node(node, ["python3", "-m", "communication.probe", "tcp", host, str(port),
                                  "--timeout", str(timeout)], timeout=timeout + 6)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "connect_ms": None, "error": r.error or r.stderr.strip() or "probe failed"}


# --------------------------------------------------------------------- host side
def host_interfaces() -> list[dict]:
    addrs, stats = psutil.net_if_addrs(), psutil.net_if_stats()
    io = psutil.net_io_counters(pernic=True)
    rows = []
    for name, alist in sorted(addrs.items()):
        st, c = stats.get(name), io.get(name)
        row = {
            "name": name,
            "is_up": st.isup if st else None,
            "speed_mbps": st.speed if st and st.speed else None,
            "mtu": st.mtu if st else None,
            "ipv4": [a.address for a in alist if a.family == socket.AF_INET],
            "ipv6": [a.address.split("%")[0] for a in alist if a.family == socket.AF_INET6],
            "mac": next((a.address for a in alist if a.family == psutil.AF_LINK), None),
            "rx_bytes": c.bytes_recv if c else None, "tx_bytes": c.bytes_sent if c else None,
            "rx_packets": c.packets_recv if c else None, "tx_packets": c.packets_sent if c else None,
            "errin": c.errin if c else None, "errout": c.errout if c else None,
            "dropin": c.dropin if c else None, "dropout": c.dropout if c else None,
        }
        row.update(_rates(("host", name), row["rx_bytes"], row["tx_bytes"], row["speed_mbps"]))
        rows.append(row)
    return rows


def _rates(key, rx, tx, capacity_mbps):
    """bit/s from two successive counter readings; utilisation only if capacity is known."""
    out = {"rx_rate_bps": None, "tx_rate_bps": None, "utilization_pct": None}
    if rx is None or tx is None:
        return out
    now = time.monotonic()
    with _last_lock:
        prev = _last.get(key)
        _last[key] = (now, rx, tx)
    if prev and now - prev[0] >= 0.2 and rx >= prev[1] and tx >= prev[2]:
        dt = now - prev[0]
        out["rx_rate_bps"] = (rx - prev[1]) * 8 / dt
        out["tx_rate_bps"] = (tx - prev[2]) * 8 / dt
        if capacity_mbps:
            out["utilization_pct"] = round(max(out["rx_rate_bps"], out["tx_rate_bps"]) / (capacity_mbps * 1e6) * 100, 3)
    return out


def host_connections(limit=60) -> dict:
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError) as exc:
        return {"total": None, "established": None, "rows": [], "error": str(exc)}
    rows = []
    for c in conns[:limit]:
        rows.append({"proto": "tcp" if c.type == socket.SOCK_STREAM else "udp",
                     "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                     "remote": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                     "status": c.status, "pid": c.pid})
    return {"total": len(conns), "established": sum(1 for c in conns if c.status == "ESTABLISHED"),
            "rows": rows, "error": None}


# --------------------------------------------------------------------- lab nodes
def node_interfaces(node: str) -> dict:
    """Interfaces of one lab node (addresses + counters) via `ip -j`."""
    r_link = netenv.run_in_node(node, ["ip", "-j", "-s", "link", "show"])
    r_addr = netenv.run_in_node(node, ["ip", "-j", "addr", "show"])
    if not r_link.ok:
        return {"node": node, "interfaces": [], "error": r_link.error or r_link.stderr.strip()}
    try:
        links = json.loads(r_link.stdout or "[]")
        addrs = {a["ifname"]: a for a in json.loads(r_addr.stdout or "[]")} if r_addr.ok else {}
    except ValueError as exc:
        return {"node": node, "interfaces": [], "error": f"bad ip output: {exc}"}
    rows = []
    for l in links:
        s = l.get("stats64") or {}
        a = addrs.get(l["ifname"], {})
        rows.append({
            "name": l["ifname"], "state": l.get("operstate", "UNKNOWN"), "mac": l.get("address"),
            "mtu": l.get("mtu"),
            "ipv4": [f"{i['local']}/{i['prefixlen']}" for i in a.get("addr_info", []) if i.get("family") == "inet"],
            "rx_bytes": s.get("rx", {}).get("bytes"), "tx_bytes": s.get("tx", {}).get("bytes"),
            "rx_packets": s.get("rx", {}).get("packets"), "tx_packets": s.get("tx", {}).get("packets"),
            "rx_errors": s.get("rx", {}).get("errors"), "rx_dropped": s.get("rx", {}).get("dropped"),
            "tx_dropped": s.get("tx", {}).get("dropped"),
        })
    return {"node": node, "interfaces": rows, "error": None}


def lab_link_counters() -> list[dict]:
    """Counters + rates for every link, read at node_a's end (in parallel)."""
    links = list(Link.objects.select_related("node_a", "node_b"))
    if not netenv.is_live():
        return []

    def read(link):
        res = node_interfaces(link.node_a.name)
        row = next((i for i in res["interfaces"] if i["name"] == link.if_a), None)
        return link, row, res.get("error")

    out = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for link, row, err in pool.map(read, links):
            entry = {"link": link.name, "state": row["state"] if row else "UNKNOWN", "error": err,
                     "capacity_mbps": link.capacity_mbps}
            if row:
                entry.update({k: row[k] for k in ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets")})
                entry.update(_rates(("link", link.name), row["rx_bytes"], row["tx_bytes"], link.capacity_mbps))
            out.append(entry)
    return out


def lab_connection_count() -> int | None:
    """Established TCP connections summed over the lab namespaces (`ss -Htan state established`)."""
    if not netenv.is_live():
        return None

    def count(node):
        r = netenv.run_in_node(node, ["ss", "-Htan", "state", "established"])
        return len([ln for ln in r.stdout.splitlines() if ln.strip()]) if r.ok else 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        # each connection is visible in two namespaces (both ends); halve the sum
        return sum(pool.map(count, netenv.LAB_NODES)) // 2


# --------------------------------------------------------------------- probing links
def probe_links(count=2) -> list[dict]:
    """Ping across every lab link (live) and update Link.status/latency/loss."""
    links = list(Link.objects.select_related("node_a", "node_b"))
    live = netenv.is_live()
    results = []
    if live:
        def one(link):
            return link, ping(link.node_a.name, link.ip_b, count=count, timeout=1)
        with ThreadPoolExecutor(max_workers=6) as pool:
            probed = list(pool.map(one, links))
        for link, p in probed:
            if p["sent"] is None and not p.get("unreachable"):
                status = Link.UNKNOWN
            elif not p["reachable"]:
                status = Link.DOWN
            elif (p["loss_pct"] or 0) > 0:
                status = Link.DEGRADED
            else:
                status = Link.UP
            link.status, link.last_checked = status, timezone.now()
            link.last_latency_ms = p["rtt_avg"] if p["reachable"] else None
            link.last_loss_pct = p["loss_pct"]
            link.save(update_fields=["status", "last_latency_ms", "last_loss_pct", "last_checked"])
            results.append({"link": link.name, "status": status, "latency_ms": link.last_latency_ms,
                            "loss_pct": link.last_loss_pct, "source": "ping", "error": p["error"]})
    else:
        # Simulation mode: no real network to measure. Status is derived from the injected
        # failure flag; latency and loss are NOT invented (left empty).
        for link in links:
            link.status = Link.DOWN if link.admin_down else Link.UP
            link.last_checked = timezone.now()
            link.last_latency_ms = link.last_loss_pct = None
            link.save(update_fields=["status", "last_latency_ms", "last_loss_pct", "last_checked"])
            results.append({"link": link.name, "status": link.status, "latency_ms": None, "loss_pct": None,
                            "source": "simulated", "error": ""})
    return results


# --------------------------------------------------------------------- snapshot
def collect_snapshot(store=True) -> dict:
    """Everything the dashboard shows, measured now. Stores MetricSample rows when store=True."""
    from .models import MetricSample
    host = host_interfaces()
    conns = host_connections(limit=0)
    io = psutil.net_io_counters()
    lab = lab_link_counters()
    lab_conn = lab_connection_count()
    snap = {
        "time": time.time(),
        "host": {
            "interfaces": len(host), "interfaces_up": sum(1 for i in host if i["is_up"]),
            "connections": conns["total"], "established": conns["established"],
            "rx_bytes": io.bytes_recv, "tx_bytes": io.bytes_sent,
            "rx_rate_bps": sum(i["rx_rate_bps"] or 0 for i in host if i["name"] != "lo"),
            "tx_rate_bps": sum(i["tx_rate_bps"] or 0 for i in host if i["name"] != "lo"),
        },
        "lab": lab,
        "lab_connections": lab_conn,
    }
    if store:
        rows = []
        for i in host:
            rows.append(MetricSample(kind="host", target=i["name"], rx_bytes=i["rx_bytes"], tx_bytes=i["tx_bytes"],
                                     rx_packets=i["rx_packets"], tx_packets=i["tx_packets"],
                                     rx_rate_bps=i["rx_rate_bps"], tx_rate_bps=i["tx_rate_bps"],
                                     utilization_pct=i["utilization_pct"]))
        for l in lab:
            rows.append(MetricSample(kind="link", target=l["link"], rx_bytes=l.get("rx_bytes"), tx_bytes=l.get("tx_bytes"),
                                     rx_packets=l.get("rx_packets"), tx_packets=l.get("tx_packets"),
                                     rx_rate_bps=l.get("rx_rate_bps"), tx_rate_bps=l.get("tx_rate_bps"),
                                     utilization_pct=l.get("utilization_pct"), latency_ms=None,
                                     active_connections=lab_conn))
        MetricSample.objects.bulk_create(rows)
    return snap


def run_command(name: str, node: str = "host", target: str = "") -> dict:
    """Run one allow-listed diagnostic command on the host or a lab node."""
    if name not in COMMANDS:
        return {"ok": False, "output": "", "error": "command not in allow-list"}
    template, needs_target = COMMANDS[name]
    argv = list(template)
    if needs_target:
        if not target:
            return {"ok": False, "output": "", "error": "this command needs a target"}
        argv.append(target)
    r = netenv.run_in_node(node, argv, timeout=25)
    return {"ok": r.ok, "command": " ".join(argv), "node": node, "output": r.text.strip(), "error": r.error,
            "duration_ms": round(r.duration_ms, 1)}
