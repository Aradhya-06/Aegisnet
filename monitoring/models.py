from django.db import models


class MetricSample(models.Model):
    """One real measurement of a host interface or a lab link.

    Every value is read from the operating system (psutil, `ip -s link`, `ping`);
    nothing is generated. A field is NULL when it could not be measured.
    """
    HOST, LINK = "host", "link"

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=10)                 # host | link
    target = models.CharField(max_length=40, db_index=True)  # interface name or link name
    rx_bytes = models.BigIntegerField(null=True, blank=True)
    tx_bytes = models.BigIntegerField(null=True, blank=True)
    rx_packets = models.BigIntegerField(null=True, blank=True)
    tx_packets = models.BigIntegerField(null=True, blank=True)
    rx_rate_bps = models.FloatField(null=True, blank=True)
    tx_rate_bps = models.FloatField(null=True, blank=True)
    utilization_pct = models.FloatField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    loss_pct = models.FloatField(null=True, blank=True)
    active_connections = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["target", "-timestamp"])]
