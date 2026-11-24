from django.db import models


class PacketCapture(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    node = models.CharField(max_length=10)
    interface = models.CharField(max_length=15)
    bpf_filter = models.CharField(max_length=120, blank=True)
    snaplen = models.PositiveIntegerField(default=512)
    duration = models.PositiveIntegerField(default=8)
    pcap_path = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, default="running")      # running | done | failed
    packet_count = models.PositiveIntegerField(default=0)
    traffic = models.JSONField(default=list, blank=True)             # generated traffic + results
    error = models.CharField(max_length=400, blank=True)
    mode = models.CharField(max_length=10, default="host")

    class Meta:
        ordering = ["-created"]


class PacketRecord(models.Model):
    capture = models.ForeignKey(PacketCapture, on_delete=models.CASCADE, related_name="packets")
    index = models.PositiveIntegerField()
    ts = models.FloatField()
    src_mac = models.CharField(max_length=17, blank=True)
    dst_mac = models.CharField(max_length=17, blank=True)
    src_ip = models.CharField(max_length=45, blank=True)
    dst_ip = models.CharField(max_length=45, blank=True)
    proto = models.CharField(max_length=8)
    app = models.CharField(max_length=6, blank=True)
    sport = models.IntegerField(null=True, blank=True)
    dport = models.IntegerField(null=True, blank=True)
    length = models.PositiveIntegerField()
    tcp_flags = models.CharField(max_length=10, blank=True)
    ttl = models.IntegerField(null=True, blank=True)
    info = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["capture", "index"]
        indexes = [models.Index(fields=["capture", "proto"])]
