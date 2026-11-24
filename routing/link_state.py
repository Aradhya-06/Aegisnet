"""Link State routing: every node knows the WHOLE topology (flooded LSAs) and runs
Dijkstra's shortest-path algorithm locally.

Dijkstra in words: keep a set of settled nodes; repeatedly settle the unsettled node
with the smallest known distance, then "relax" its links (if going through it is
shorter for a neighbour, update that neighbour's distance and predecessor).
"""
from __future__ import annotations

import heapq

from .topology import Graph, TopologyError


def dijkstra(graph: Graph, source: str):
    """Return (dist, prev, steps). Ties are broken alphabetically so results are deterministic."""
    if source not in graph.nodes:
        raise TopologyError(f"unknown node {source!r}")
    dist = {n: float("inf") for n in graph.nodes}
    prev: dict[str, str | None] = {n: None for n in graph.nodes}
    dist[source] = 0
    heap = [(0, source)]
    settled: set[str] = set()
    steps = []
    while heap:
        d, u = heapq.heappop(heap)
        if u in settled:
            continue
        settled.add(u)
        steps.append(f"settle {u} (distance {d})")
        for v, cost in sorted(graph.neighbors(u).items()):
            if v in settled:
                continue
            if d + cost < dist[v]:
                steps.append(f"  relax {u}-{v}: {d} + {cost} = {d + cost} < {dist[v] if dist[v] != float('inf') else 'inf'} -> {v} reached via {u}")
                dist[v], prev[v] = d + cost, u
                heapq.heappush(heap, (dist[v], v))
    return dist, prev, steps


def path_to(prev: dict, source: str, dest: str):
    if prev.get(dest) is None and dest != source:
        return None
    path, node = [dest], dest
    while node != source:
        node = prev[node]
        path.append(node)
    return list(reversed(path))


def shortest_path(graph: Graph, source: str, dest: str) -> dict:
    if dest not in graph.nodes:
        raise TopologyError(f"unknown node {dest!r}")
    dist, prev, steps = dijkstra(graph, source)
    path = path_to(prev, source, dest)
    return {"path": path, "cost": dist[dest] if path else None, "steps": steps}


def routing_table(graph: Graph, source: str) -> list[dict]:
    """Forwarding table of `source`: for each destination the NEXT HOP, total cost and full path."""
    dist, prev, _ = dijkstra(graph, source)
    rows = []
    for dest in sorted(graph.nodes):
        if dest == source:
            continue
        path = path_to(prev, source, dest)
        rows.append({"dest": dest, "next_hop": path[1] if path else None,
                     "cost": dist[dest] if path else None, "path": path})
    return rows


def run_link_state(graph: Graph, source: str, dest: str) -> dict:
    sp = shortest_path(graph, source, dest)
    tables = {n: routing_table(graph, n) for n in sorted(graph.nodes)}
    lsdb = [{"a": sorted(k)[0], "b": sorted(k)[1], "cost": v["cost"], "state": "up" if v["enabled"] else "down"}
            for k, v in sorted(graph.links.items(), key=lambda kv: sorted(kv[0]))]
    return {"algorithm": "link_state", "path": sp["path"], "cost": sp["cost"], "steps": sp["steps"],
            "tables": tables, "lsdb": lsdb}
