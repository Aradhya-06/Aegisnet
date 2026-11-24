from django.db import models

from core.models import Link, Node


class ThresholdConfig(models.Model):
    key = models.CharField(max_length=30, unique=True)
    value = models.FloatField()
    enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["key"]


class MonitoredFlow(models.Model):
    """An end-to-end path that must keep working (e.g. PC A -> PC B)."""
    name = models.CharField(max_length=30, unique=True)
    src = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="flows_from")
    dst = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="flows_to")
    enabled = models.BooleanField(default=True)
    primary_path = models.JSONField(default=list)     # node names
    current_path = models.JSONField(default=list)     # path the recovery engine last installed
    status = models.CharField(max_length=10, default="unknown")   # up | down | unknown
    last_latency_ms = models.FloatField(null=True, blank=True)
    last_loss_pct = models.FloatField(null=True, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]


class Alert(models.Model):
    KINDS = [
        ("node_unreachable", "Node unreachable"), ("interface_down", "Interface down"), ("link_down", "Link failure"),
        ("high_latency", "High latency"), ("packet_loss", "Packet loss"), ("high_utilization", "High utilisation"),
        ("service_down", "TCP service unavailable"), ("flow_unreachable", "End-to-end path broken"),
    ]
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved = models.BooleanField(default=False, db_index=True)
    kind = models.CharField(max_length=20, choices=KINDS)
    severity = models.CharField(max_length=10)               # critical | warning
    target = models.CharField(max_length=40)                 # link / node / flow / service name
    reason = models.CharField(max_length=300)
    suggested_action = models.CharField(max_length=300, blank=True)
    mode = models.CharField(max_length=10, default="live")   # live | simulated
    link = models.ForeignKey(Link, null=True, blank=True, on_delete=models.SET_NULL)
    flow = models.ForeignKey(MonitoredFlow, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created"]


class FailureInjection(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    kind = models.CharField(max_length=10, default="link")   # link | service | restore
    target = models.CharField(max_length=40)
    dry_run = models.BooleanField(default=False)
    mode = models.CharField(max_length=10)
    ok = models.BooleanField(default=False)
    output = models.TextField(blank=True)

    class Meta:
        ordering = ["-created"]


class RecoveryEvent(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    alert = models.ForeignKey(Alert, null=True, blank=True, on_delete=models.SET_NULL)
    flow = models.ForeignKey(MonitoredFlow, on_delete=models.CASCADE)
    failed_links = models.JSONField(default=list)
    old_path = models.JSONField(default=list)
    new_path = models.JSONField(default=list)
    commands = models.JSONField(default=list)       # [{node, command, ok, output}]
    mode = models.CharField(max_length=10)          # live | simulated
    dry_run = models.BooleanField(default=False)
    result = models.CharField(max_length=12)        # success | failed | no_path | no_change | dry_run
    verified = models.BooleanField(default=False)
    verification = models.CharField(max_length=300, blank=True)
    message = models.CharField(max_length=300, blank=True)
    duration_ms = models.FloatField(null=True, blank=True)
    trigger = models.CharField(max_length=10, default="manual")   # manual | auto

    class Meta:
        ordering = ["-created"]
