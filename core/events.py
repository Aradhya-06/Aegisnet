"""Tiny helper so every module writes to the same dashboard timeline."""
from .models import EventLog


def log_event(source: str, message: str, level: str = EventLog.INFO, **details) -> EventLog:
    return EventLog.objects.create(source=source, message=message[:300], level=level, details=details)
