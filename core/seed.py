"""Idempotent seeding of the lab topology, flows, thresholds."""
from . import topology_def as T
from .models import Link, Node


def seed_core():
    nodes = {}
    for name, label, kind, ip, x, y in T.NODES:
        nodes[name], _ = Node.objects.update_or_create(
            name=name, defaults=dict(label=label, kind=kind, ip_primary=ip, x=x, y=y))
    for name, a, b, ifa, ifb, ipa, ipb, subnet, cost, primary in T.LINKS:
        Link.objects.update_or_create(
            name=name,
            defaults=dict(node_a=nodes[a], node_b=nodes[b], if_a=ifa, if_b=ifb, ip_a=ipa, ip_b=ipb,
                          subnet=subnet, is_primary=primary),
        )
        # keep an operator-edited cost; only set it when the link is new
        Link.objects.filter(name=name, cost=1).update(cost=cost)
    return nodes
