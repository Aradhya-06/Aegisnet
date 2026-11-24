from django.db import models


class SandboxTopology(models.Model):
    """A user-drawn practice topology (never applied to the Linux lab)."""
    name = models.CharField(max_length=60, unique=True)
    data = models.JSONField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
