from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("about/", views.about, name="about"),
    path("api/dashboard/", views.api_dashboard, name="api_dashboard"),
    path("api/probe/", views.api_probe_all, name="api_probe"),
]
