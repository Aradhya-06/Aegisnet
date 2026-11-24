from django.urls import path

from . import views

app_name = "communication"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/services/", views.api_services, name="api_services"),
    path("api/service/", views.api_service_action, name="api_service_action"),
    path("api/send/", views.api_send, name="api_send"),
    path("api/compare/", views.api_compare, name="api_compare"),
    path("api/history/", views.api_history, name="api_history"),
]
