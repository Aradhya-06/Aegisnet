"""Shared models: the lab topology (single source of truth), event log, processes."""
from django.db import models


class Node(models.Model):
    HOST, ROUTER = "host", "router"
    KINDS = [(HOST, "Host"), (ROUTER, "Router")]

    name = models.SlugField(max_length=20, unique=True)          # "a", "r1" ...
    label = models.CharField(max_length=40)                      # "PC A"
    kind = models.CharField(max_length=10, choices=KINDS)
    ip_primary = models.GenericIPAddressField(null=True, blank=True)  # host address used in tests
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)

    class Meta:
        ordering = ["name"]

    @property
    def namespace(self):
        return f"aegis_{self.name}"

    def __str__(self):
        return self.label


class Link(models.Model):
    UP, DOWN, DEGRADED, UNKNOWN = "up", "down", "degraded", "unknown"
    STATUSES = [(UP, "Up"), (DOWN, "Down"), (DEGRADED, "Degraded"), (UNKNOWN, "Unknown")]

    name = models.SlugField(max_length=20, unique=True)          # "r1-r2"
    node_a = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="links_a")
    node_b = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="links_b")
    if_a = models.CharField(max_length=15)
    if_b = models.CharField(max_length=15)
    ip_a = models.GenericIPAddressField()
    ip_b = models.GenericIPAddressField()
    subnet = models.CharField(max_length=20)
    cost = models.PositiveIntegerField(default=1)
    capacity_mbps = models.PositiveIntegerField(default=100, help_text="Configured nominal capacity used for utilisation %")
    is_primary = models.BooleanField(default=True)
    # admin_down: a failure was injected (simulated mode derives status from this)
    admin_down = models.BooleanField(default=False)
    # status is what probes OBSERVED (live mode) or derived from admin_down (simulated)
    status = models.CharField(max_length=10, choices=STATUSES, default=UNKNOWN)
    last_latency_ms = models.FloatField(null=True, blank=True)
    last_loss_pct = models.FloatField(null=True, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def other(self, node):
        return self.node_b if node.pk == self.node_a.pk else self.node_a

    def ip_of(self, node):
        return self.ip_a if node.pk == self.node_a.pk else self.ip_b

    def iface_of(self, node):
        return self.if_a if node.pk == self.node_a.pk else self.if_b

    def __str__(self):
        return self.name


class EventLog(models.Model):
    INFO, SUCCESS, WARNING, ERROR = "info", "success", "warning", "error"
    LEVELS = [(INFO, "info"), (SUCCESS, "success"), (WARNING, "warning"), (ERROR, "error")]

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    source = models.CharField(max_length=30)
    level = models.CharField(max_length=10, choices=LEVELS, default=INFO)
    message = models.CharField(max_length=300)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]


class ManagedProcess(models.Model):
    """A long-running helper started from the UI (test server, detector)."""
    RUNNING, STOPPED = "running", "stopped"

    name = models.CharField(max_length=40, unique=True)
    kind = models.CharField(max_length=20)
    node = models.CharField(max_length=10, blank=True)
    command = models.TextField()
    pid = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, default=STOPPED)
    # expected_up: the operator wants it running. A crash/injected failure leaves this True,
    # so the fault detector can notice "should be up but is not".
    expected_up = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    log_path = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["name"]
