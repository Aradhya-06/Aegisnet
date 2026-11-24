"""Distance Vector routing (distributed Bellman-Ford), simulated round by round.

Each node knows only its direct neighbours at first. In every ROUND all nodes send
their distance table to their neighbours; a node updates a route when
    cost(link to neighbour) + neighbour's advertised cost  <  its current cost
or when its current next hop reports a changed cost (it must follow its next hop).
Convergence = a round in which nobody changes anything.

"Infinity" is 16 (like RIP). With split_horizon=False the classic COUNT-TO-INFINITY
problem can be observed after a link fails: use `previous_tables` to continue from the
tables of the topology BEFORE the change.
"""
from __future__ import annotations

import copy

from .topology import INF, Graph, TopologyError

Table = dict  # dest -> (cost, next_hop)


def initial_tables(graph: Graph) -> dict[str, Table]:
    tables = {n: {n: (0, n)} for n in graph.nodes}
    for n in graph.nodes:
        for nb, cost in graph.neighbors(n).items():
            tables[n][nb] = (cost, nb)
    return tables


def converge(graph: Graph, tables: dict[str, Table] | None = None, split_horizon: bool = True,
             max_rounds: int = 60) -> dict:
    """Run synchronous rounds until stable. Returns tables, a log per round and convergence info."""
    for n in graph.nodes:
        if not isinstance(n, str):
            raise TopologyError("node ids must be strings")
    if tables is None:
        tables = initial_tables(graph)
        log = [{"round": 0, "updates": ["each node starts knowing only its directly connected neighbours"]}]
    else:
        tables = copy.deepcopy(tables)
        log = [{"round": 0, "updates": []}]
        for n in sorted(graph.nodes):
            direct = graph.neighbors(n)
            for dest, (cost, nh) in list(tables.get(n, {}).items()):
                if dest == n:
                    continue
                if nh not in direct:                    # link to the next hop is gone
                    tables[n][dest] = (INF, nh)
                    log[0]["updates"].append(f"{n}: next hop {nh} for {dest} is no longer reachable -> cost {INF} (unreachable)")
            for nb, cost in direct.items():             # newly (re)enabled or cheaper direct link
                cur = tables[n].get(nb)
                if cur is None or cost < cur[0]:
                    tables[n][nb] = (cost, nb)
                    log[0]["updates"].append(f"{n}: direct link to {nb} costs {cost}")
        if not log[0]["updates"]:
            log[0]["updates"].append("topology unchanged - tables already consistent")

    converged_round = None
    for rnd in range(1, max_rounds + 1):
        snapshot = copy.deepcopy(tables)            # everybody advertises the tables from the START of the round
        updates = []
        for n in sorted(graph.nodes):
            for nb, link_cost in sorted(graph.neighbors(n).items()):
                for dest, (c, nh) in snapshot[nb].items():
                    if dest == n:
                        continue
                    if split_horizon and nh == n and dest != nb:
                        continue                    # do not advertise a route back to the node it came from
                    new_cost = min(INF, link_cost + c)
                    cur = tables[n].get(dest)
                    if cur is None:
                        if new_cost < INF:
                            tables[n][dest] = (new_cost, nb)
                            updates.append(f"{n}: learned route to {dest} via {nb}, cost {new_cost}")
                    elif cur[1] == nb:
                        if new_cost != cur[0]:      # next hop changed its mind: follow it
                            tables[n][dest] = (new_cost, nb)
                            updates.append(f"{n}: route to {dest} via {nb} changed cost {cur[0]} -> {new_cost}")
                    elif new_cost < cur[0]:
                        tables[n][dest] = (new_cost, nb)
                        updates.append(f"{n}: better route to {dest} via {nb}, cost {cur[0]} -> {new_cost}")
        log.append({"round": rnd, "updates": updates or ["no changes - converged"]})
        if not updates:
            converged_round = rnd - 1
            break
    out_tables = {n: _table_rows(tables[n]) for n in sorted(tables)}
    return {"algorithm": "distance_vector", "raw": tables, "tables": out_tables, "rounds": log,
            "converged": converged_round is not None, "rounds_to_converge": converged_round,
            "split_horizon": split_horizon,
            # many more rounds than nodes = routes slowly counting up to "infinity"
            "count_to_infinity": (not split_horizon) and (converged_round is None or converged_round > len(graph.nodes))}


def _table_rows(table: Table) -> list[dict]:
    rows = []
    for dest in sorted(table):
        cost, nh = table[dest]
        if cost == 0:
            continue
        rows.append({"dest": dest, "next_hop": nh if cost < INF else None, "cost": cost if cost < INF else None})
    return rows


def path_from_tables(raw: dict[str, Table], source: str, dest: str):
    """Follow next hops from source to dest. Returns (path or None, problem message or None)."""
    path, node, seen = [source], source, {source}
    while node != dest:
        entry = raw.get(node, {}).get(dest)
        if not entry or entry[0] >= INF:
            return None, f"{node} has no route to {dest}"
        node = entry[1]
        if node in seen:
            return None, f"routing loop detected at {node}"
        seen.add(node)
        path.append(node)
        if len(path) > len(raw) + 1:
            return None, "path too long"
    return path, None


def run_distance_vector(graph: Graph, source: str, dest: str, split_horizon=True, previous_graph: Graph | None = None) -> dict:
    for n in (source, dest):
        if n not in graph.nodes:
            raise TopologyError(f"unknown node {n!r}")
    previous = None
    if previous_graph is not None:
        previous = converge(previous_graph, None, split_horizon)["raw"]
    res = converge(graph, previous, split_horizon)
    path, problem = path_from_tables(res["raw"], source, dest)
    cost = res["raw"][source].get(dest, (None,))[0] if path else None
    res.update(path=path, cost=cost, problem=problem, continued_from_previous=previous is not None)
    res.pop("raw")
    return res
