from core import topology_def as T
from core.models import Node

from .models import MonitoredFlow, ThresholdConfig


def seed_recovery():
    for key, value, desc in T.THRESHOLDS:
        ThresholdConfig.objects.get_or_create(key=key, defaults=dict(value=value, description=desc))
    nodes = {n.name: n for n in Node.objects.all()}
    for name, src, dst, path in T.FLOWS:
        flow, created = MonitoredFlow.objects.get_or_create(
            name=name, defaults=dict(src=nodes[src], dst=nodes[dst], primary_path=path, current_path=path))
        if not created and not flow.primary_path:
            flow.primary_path = flow.current_path = path
            flow.save()
