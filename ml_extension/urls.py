from django.urls import path

from . import views

app_name = "ml_extension"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/collect/", views.api_collect, name="api_collect"),
    path("api/upload/", views.api_upload, name="api_upload"),
    path("api/train/", views.api_train, name="api_train"),
    path("api/predict/", views.api_predict, name="api_predict"),
]
