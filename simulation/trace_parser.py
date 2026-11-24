"""Parse an NS2 trace file and compute throughput, delay, PDR and loss per flow.

NS2 trace line:   event time from to type size flags fid src dst seq pktid
                  r     1.23 0    1  tcp  1000 ------- 1   0.0 4.0 12  34
  event: + enqueue, - dequeue, r receive (at the 'to' node), d drop.
  from/to are the two ends of the LINK the event happened on; src/dst are
  node.port of the flow's end points.

Definitions used (and shown in the UI):
  sent       packets enqueued ('+') at the flow's SOURCE node on its first hop
  delivered  packets received ('r') at the flow's DESTINATION node
  PDR        delivered / sent           loss ratio = 1 - PDR
             (packets still in flight when the simulation ends count as not delivered;
              the scenarios stop the sources 0.5 s before the end to keep this small)
  delay      receive time - first enqueue time of the same packet (end to end)
  throughput delivered bits / (last delivery time - first send time)
Routing-protocol packets (rtProtoDV) and TCP ACKs are excluded from the data-flow metrics.
Pure Python, no Django.
"""
from __future__ import annotations

from collections import defaultdict

DATA_TYPES = {"tcp", "cbr", "udp", "exp", "pareto"}
BIN = 0.5            # seconds per time-series bin


def _node(addr: str) -> int:
    return int(float(addr))


def parse_trace(lines, labels: dict | None = None) -> dict:
    """lines: iterable of trace lines. labels: optional {fid: "TCP A->B"}."""
    labels = labels or {}
    flows = defaultdict(lambda: {"type": None, "src": None, "dst": None, "sent": {}, "recv": {}, "dropped": set(),
                                 "bytes_recv": 0, "series_bytes": defaultdict(int), "series_delay": defaultdict(list)})
    last_time = 0.0
    routing_packets = 0
    for line in lines:
        f = line.split()
        if len(f) < 12:
            continue
        ev, t, frm, to, ptype = f[0], float(f[1]), int(f[2]), int(f[3]), f[4]
        last_time = max(last_time, t)
        if ptype.startswith("rtProto") or ptype == "rtProtoDV":
            routing_packets += 1
            continue
        if ptype not in DATA_TYPES:
            continue
        size, fid = int(f[5]), int(f[7])
        src, dst, pktid = _node(f[8]), _node(f[9]), int(f[11])
        fl = flows[fid]
        fl["type"], fl["src"], fl["dst"] = ptype, src, dst
        if ev == "+" and frm == src and pktid not in fl["sent"]:
            fl["sent"][pktid] = t
        elif ev == "r" and to == dst and pktid not in fl["recv"]:
            fl["recv"][pktid] = t
            fl["bytes_recv"] += size
            b = int(t // BIN)
            fl["series_bytes"][b] += size
            if pktid in fl["sent"]:
                fl["series_delay"][b].append(t - fl["sent"][pktid])
        elif ev == "d":
            fl["dropped"].add(pktid)

    out_flows = {}
    for fid, fl in sorted(flows.items()):
        sent, recv = fl["sent"], fl["recv"]
        delays = [recv[p] - sent[p] for p in recv if p in sent]
        n_sent, n_recv = len(sent), len(recv)
        t_start = min(sent.values()) if sent else 0.0
        t_end = max(recv.values()) if recv else t_start
        span = max(t_end - t_start, 1e-9)
        out_flows[fid] = {
            "fid": fid, "label": labels.get(fid, f"{fl['type']} node{fl['src']}->node{fl['dst']}"),
            "type": fl["type"], "src_node": fl["src"], "dst_node": fl["dst"],
            "sent": n_sent, "delivered": n_recv, "dropped": len(fl["dropped"]),
            "pdr": round(n_recv / n_sent, 4) if n_sent else None,
            "loss_ratio": round(1 - n_recv / n_sent, 4) if n_sent else None,
            "throughput_bps": round(fl["bytes_recv"] * 8 / span, 1) if n_recv else 0.0,
            "avg_delay_ms": round(sum(delays) / len(delays) * 1000, 3) if delays else None,
            "max_delay_ms": round(max(delays) * 1000, 3) if delays else None,
            "series": [{"t": round(b * BIN, 2),
                        "throughput_bps": round(fl["series_bytes"].get(b, 0) * 8 / BIN, 1),
                        "delay_ms": round(sum(fl["series_delay"][b]) / len(fl["series_delay"][b]) * 1000, 3)
                        if fl["series_delay"].get(b) else None}
                       for b in range(0, int(last_time // BIN) + 1)],
        }
    return {"flows": out_flows, "duration": last_time, "routing_packets": routing_packets}


def parse_trace_file(path, labels=None) -> dict:
    with open(path, "r", errors="replace") as fh:
        return parse_trace(fh, labels)
