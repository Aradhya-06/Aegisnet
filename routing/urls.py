from django.urls import path

from . import views

app_name = "routing"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/lab/", views.api_lab, name="api_lab"),
    path("api/run/", views.api_run, name="api_run"),
    path("api/save/", views.api_save, name="api_save"),
    path("api/saved/", views.api_saved, name="api_saved"),
    path("api/kernel-routes/", views.api_kernel_routes, name="api_kernel_routes"),
]
