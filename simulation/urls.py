from django.urls import path

from . import views

app_name = "simulation"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/run/", views.api_run, name="api_run"),
    path("api/compare/", views.api_compare, name="api_compare"),
    path("api/run/<int:pk>/", views.api_run_detail, name="api_run_detail"),
    path("api/script/", views.api_script, name="api_script"),
]
