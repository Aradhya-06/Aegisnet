from django.urls import path

from . import views

app_name = "packet_analyzer"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/capture/", views.api_capture, name="api_capture"),
    path("api/interfaces/", views.api_interfaces, name="api_interfaces"),
    path("capture/<int:pk>/", views.detail, name="detail"),
    path("capture/<int:pk>/download/", views.download, name="download"),
    path("capture/<int:pk>/tshark/", views.tshark, name="tshark"),
]
