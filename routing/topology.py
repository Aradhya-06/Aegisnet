"""Graph model used by the routing algorithms (educational, pure Python).

IMPORTANT: this graph is a MODEL of a network. Running an algorithm on it computes
routes on paper; it does not touch any Linux routing table. Only the recovery
engine applies routes to the lab namespaces, and it says so explicitly.
"""
from __future__ import annotations

INF = 16        # "infinity" for distance vector, like RIP (max hop count 15)


class TopologyError(ValueError):
    pass


class Graph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}          # id -> {"label":..., "x":..., "y":...}
        self.links: dict[frozenset, dict] = {}    # {a,b} -> {"cost": int, "enabled": bool}

    # ----- building
    def add_node(self, node_id: str, label: str | None = None, x: float = 0, y: float = 0):
        node_id = str(node_id).strip()
        if not node_id:
            raise TopologyError("node id must not be empty")
        self.nodes.setdefault(node_id, {"label": label or node_id, "x": x, "y": y})

    def add_link(self, a: str, b: str, cost: int = 1, enabled: bool = True):
        if a == b:
            raise TopologyError("a link needs two different nodes")
        for n in (a, b):
            if n not in self.nodes:
                raise TopologyError(f"unknown node {n!r}")
        try:
            cost = int(cost)
        except (TypeError, ValueError):
            raise TopologyError("link cost must be an integer")
        if not 1 <= cost <= 1000:
            raise TopologyError("link cost must be between 1 and 1000")
        self.links[frozenset((a, b))] = {"cost": cost, "enabled": bool(enabled)}

    # ----- queries
    def neighbors(self, node: str) -> dict[str, int]:
        """Reachable neighbours over ENABLED links: {neighbour: cost}."""
        out = {}
        for key, link in self.links.items():
            if node in key and link["enabled"]:
                (other,) = key - {node}
                out[other] = link["cost"]
        return out

    def link_cost(self, a: str, b: str):
        link = self.links.get(frozenset((a, b)))
        return link["cost"] if link and link["enabled"] else None

    # ----- (de)serialisation for the browser
    @classmethod
    def from_json(cls, data: dict) -> "Graph":
        g = cls()
        nodes = data.get("nodes", [])
        if not isinstance(nodes, list) or len(nodes) > 40:
            raise TopologyError("topology must have at most 40 nodes")
        for n in nodes:
            g.add_node(n["id"], n.get("label"), n.get("x", 0), n.get("y", 0))
        for l in data.get("links", []):
            g.add_link(l["a"], l["b"], l.get("cost", 1), l.get("enabled", True))
        return g

    def to_json(self) -> dict:
        return {
            "nodes": [{"id": k, **v} for k, v in self.nodes.items()],
            "links": [{"a": sorted(k)[0], "b": sorted(k)[1], **v} for k, v in self.links.items()],
        }
