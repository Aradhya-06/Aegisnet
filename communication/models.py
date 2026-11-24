from django.db import models


class TransferSession(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    proto = models.CharField(max_length=5)                   # tcp | udp
    src_node = models.CharField(max_length=10)
    dst_host = models.GenericIPAddressField()
    dst_port = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, default="message")   # message | file
    filename = models.CharField(max_length=120, blank=True)
    bytes_sent = models.BigIntegerField(default=0)
    status = models.CharField(max_length=20)
    ok = models.BooleanField(default=False)
    connect_ms = models.FloatField(null=True, blank=True)
    total_ms = models.FloatField(null=True, blank=True)
    response = models.TextField(blank=True)
    error = models.CharField(max_length=300, blank=True)
    steps = models.JSONField(default=list, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    mode = models.CharField(max_length=10, default="host")   # live | host

    class Meta:
        ordering = ["-created"]
