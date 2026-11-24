"""Definition of the lab topology. Mirrors scripts/lab_common.sh (a test checks it)."""

NODES = [
    # name, label, kind, host ip, x, y   (x/y only used by the topology drawing)
    ("a", "PC A", "host", "10.10.1.1", 70, 150),
    ("r1", "Router R1", "router", None, 230, 150),
    ("r2", "Router R2", "router", None, 470, 150),
    ("b", "PC B", "host", "10.10.5.2", 660, 150),
    ("r3", "Router R3", "router", None, 350, 320),
    ("c", "PC C", "host", "10.10.6.2", 560, 330),
]

# name, node_a, node_b, if_a, if_b, ip_a, ip_b, subnet, cost, is_primary
LINKS = [
    ("a-r1", "a", "r1", "a-r1", "r1-a", "10.10.1.1", "10.10.1.2", "10.10.1.0/30", 1, True),
    ("r1-r2", "r1", "r2", "r1-r2", "r2-r1", "10.10.2.1", "10.10.2.2", "10.10.2.0/30", 1, True),
    ("r1-r3", "r1", "r3", "r1-r3", "r3-r1", "10.10.3.1", "10.10.3.2", "10.10.3.0/30", 1, False),
    ("r3-r2", "r3", "r2", "r3-r2", "r2-r3", "10.10.4.1", "10.10.4.2", "10.10.4.0/30", 1, False),
    ("r2-b", "r2", "b", "r2-b", "b-r2", "10.10.5.1", "10.10.5.2", "10.10.5.0/30", 1, True),
    ("r3-c", "r3", "c", "r3-c", "c-r3", "10.10.6.1", "10.10.6.2", "10.10.6.0/30", 1, True),
]

# Monitored end-to-end flows: name, src, dst, primary path
FLOWS = [
    ("A to B", "a", "b", ["a", "r1", "r2", "b"]),
    ("A to C", "a", "c", ["a", "r1", "r3", "c"]),
    ("B to C", "b", "c", ["b", "r2", "r3", "c"]),
]

# key, value, description
THRESHOLDS = [
    ("latency_ms", 20.0, "Warn when average round-trip latency exceeds this many ms"),
    ("loss_pct", 5.0, "Warn when packet loss exceeds this percentage"),
    ("utilization_pct", 80.0, "Warn when link utilisation exceeds this percentage of its configured capacity"),
]

# Test services that should be running when the lab is demonstrated:
# name, node, proto, port
SERVICES = [
    ("tcp-b", "b", "tcp", 9001),
    ("udp-b", "b", "udp", 9002),
    ("tcp-c", "c", "tcp", 9001),
    ("udp-c", "c", "udp", 9002),
    ("http-b", "b", "tcp", 8080),
    ("dns-b", "b", "udp", 5353),
    ("tls-b", "b", "tcp", 8443),
]
