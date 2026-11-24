from django.urls import path

from . import views

app_name = "monitoring"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/interfaces/", views.api_interfaces, name="api_interfaces"),
    path("api/connections/", views.api_connections, name="api_connections"),
    path("api/ping/", views.api_ping, name="api_ping"),
    path("api/command/", views.api_command, name="api_command"),
    path("api/probe/", views.api_probe, name="api_probe"),
    path("api/history/", views.api_history, name="api_history"),
]
