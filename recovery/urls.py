from django.urls import path

from . import views

app_name = "recovery"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/state/", views.api_state, name="api_state"),
    path("api/inject/", views.api_inject, name="api_inject"),
    path("api/restore/", views.api_restore, name="api_restore"),
    path("api/detect/", views.api_detect, name="api_detect"),
    path("api/recover/", views.api_recover, name="api_recover"),
    path("api/detector/", views.api_detector, name="api_detector"),
    path("api/service-failure/", views.api_service_failure, name="api_service_failure"),
    path("api/threshold/", views.api_threshold, name="api_threshold"),
]
