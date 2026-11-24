"""Lab topology as a routing Graph (shared by the routing views and the recovery engine)."""
from core import netenv
from core.models import Link, Node

from .topology import Graph


def lab_graph() -> Graph:
    """Nodes and links from the database. A link counts as disabled when it is observed down
    (live mode) or has an injected failure (simulated mode)."""
    live = netenv.is_live()
    g = Graph()
    for n in Node.objects.all():
        g.add_node(n.name, n.label, n.x, n.y)
    for l in Link.objects.select_related("node_a", "node_b"):
        down = (l.status == Link.DOWN) if live else l.admin_down
        g.add_link(l.node_a.name, l.node_b.name, l.cost, enabled=not down)
    return g
