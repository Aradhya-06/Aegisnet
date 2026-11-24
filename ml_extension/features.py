"""Feature definitions shared by data collection, training and prediction."""

FEATURES = ["utilization_pct", "throughput_mbps", "latency_ms", "loss_pct", "active_connections", "packets_per_sec"]
LABELS = ["normal", "moderate", "high"]

DESCRIPTIONS = {
    "utilization_pct": "Link utilisation: egress rate / configured link capacity x 100 (from interface byte counters).",
    "throughput_mbps": "Measured egress throughput of the link in Mbit/s (counter difference / time).",
    "latency_ms": "Average round-trip time of a ping across the loaded path (ms).",
    "loss_pct": "Packet loss reported by that ping (%).",
    "active_connections": "Established TCP connections seen in the lab namespaces (ss).",
    "packets_per_sec": "Egress packet rate of the link (packets/s).",
}


def threshold_baseline(row) -> str:
    """The conventional rule-based detector the ML model is compared with.
    Rules: high if utilisation >= 85 % or loss >= 5 %; moderate if utilisation >= 50 % or
    loss >= 1 % or latency >= 20 ms; otherwise normal."""
    util = row["utilization_pct"] or 0
    loss = row["loss_pct"] or 0
    lat = row["latency_ms"] or 0
    if util >= 85 or loss >= 5:
        return "high"
    if util >= 50 or loss >= 1 or lat >= 20:
        return "moderate"
    return "normal"
