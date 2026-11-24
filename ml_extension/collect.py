"""Collect a LABELLED congestion dataset from the live lab (never invented).

Ground truth = the experimental condition WE apply: the link R1-R2 is shaped to 10 Mbit/s
(tc tbf) and a UDP load of 2 / 8 / 15 Mbit/s is offered from PC A to PC B:
    normal (2 Mb/s = 20 %)   moderate (8 Mb/s = 80 %)   high (15 Mb/s = 150 % -> queue overflow, loss)
Every second we MEASURE the features from the real link counters and ping. Needs the live
lab, root helpers and the kernel module sch_tbf; otherwise it stops with a clear message.
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

from django.conf import settings

from communication import services as comm
from core import netenv
from core.models import Link, Node
from monitoring import services as mon

from .features import FEATURES

LEVELS = [("normal", 2.0), ("moderate", 8.0), ("high", 15.0)]
LINK = "r1-r2"
SHAPED_MBIT = 10


class CollectError(RuntimeError):
    pass


def dataset_path() -> Path:
    return settings.DATA_DIR / "ml" / "dataset.csv"


def collect(samples_per_level=40, skip_shaping=False, log=print) -> int:
    if not netenv.is_live():
        raise CollectError("the live namespace lab is required (run scripts/setup_network.sh)")
    link = Link.objects.get(name=LINK)
    b_ip = Node.objects.get(name="b").ip_primary
    old_capacity = link.capacity_mbps
    if not skip_shaping:
        r = netenv.run_script("impair_link.sh", LINK, "rate", str(SHAPED_MBIT))
        if not r.ok:
            raise CollectError("cannot shape the link (kernel module sch_tbf missing or no root): " + (r.error or r.text)[-200:])
        link.capacity_mbps = SHAPED_MBIT
        link.save(update_fields=["capacity_mbps"])
    comm.start_service("udp-b")
    path = dataset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    rows = 0
    try:
        with open(path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(FEATURES + ["label"])
            for label, mbps in LEVELS:
                log(f"load level {label}: offering {mbps} Mbit/s for ~{samples_per_level + 3}s")
                gen = netenv.popen_in_node("a", ["python3", "-m", "communication.loadgen", "--host", b_ip, "--port", "9002",
                                                 "--mbps", str(mbps), "--seconds", str(samples_per_level + 3)])
                time.sleep(2)
                prev = None
                for _ in range(samples_per_level):
                    t0 = time.monotonic()
                    res = mon.node_interfaces(link.node_a.name)
                    row = next((i for i in res["interfaces"] if i["name"] == link.if_a), None)
                    ping = mon.ping("a", b_ip, count=2, timeout=1)
                    now = time.monotonic()
                    if row and prev and now > prev[0]:
                        dt = now - prev[0]
                        tx_bps = (row["tx_bytes"] - prev[1]) * 8 / dt
                        pps = (row["tx_packets"] - prev[2]) / dt
                        sample = {"utilization_pct": round(tx_bps / (link.capacity_mbps * 1e6) * 100, 3),
                                  "throughput_mbps": round(tx_bps / 1e6, 4),
                                  "latency_ms": ping["rtt_avg"] if ping["rtt_avg"] is not None else 1000.0,
                                  "loss_pct": ping["loss_pct"] if ping["loss_pct"] is not None else 100.0,
                                  "active_connections": mon.lab_connection_count() or 0,
                                  "packets_per_sec": round(pps, 2)}
                        w.writerow([sample[f] for f in FEATURES] + [label])
                        rows += 1
                    if row:
                        prev = (now, row["tx_bytes"], row["tx_packets"])
                    time.sleep(max(0, 1.0 - (time.monotonic() - t0)))
                gen.wait(timeout=30)
    finally:
        if not skip_shaping:
            netenv.run_script("impair_link.sh", LINK, "clear")
            link.capacity_mbps = old_capacity
            link.save(update_fields=["capacity_mbps"])
    return rows
