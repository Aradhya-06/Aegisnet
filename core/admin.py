from django.contrib import admin

from .models import EventLog, Link, ManagedProcess, Node

admin.site.register(Node)
admin.site.register(Link)
admin.site.register(EventLog)
admin.site.register(ManagedProcess)
