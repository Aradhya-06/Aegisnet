from django.db import models


class SimulationRun(models.Model):
    """One attempt to run an NS2 scenario.

    `executed` is True ONLY when NS2 really ran and produced a trace file. If NS2 is
    not installed the run is recorded with status "not_available" and no metrics.
    """
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    scenario = models.CharField(max_length=20)
    status = models.CharField(max_length=15, default="running")   # running | completed | failed | not_available
    executed = models.BooleanField(default=False)
    return_code = models.IntegerField(null=True, blank=True)
    duration_s = models.FloatField(null=True, blank=True)
    ns_path = models.CharField(max_length=200, blank=True)
    trace_path = models.CharField(max_length=300, blank=True)
    log_tail = models.TextField(blank=True)
    metrics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created"]
