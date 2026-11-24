from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("core.urls")),
    path("monitoring/", include("monitoring.urls")),
    path("communication/", include("communication.urls")),
    path("packets/", include("packet_analyzer.urls")),
    path("routing/", include("routing.urls")),
    path("simulation/", include("simulation.urls")),
    path("recovery/", include("recovery.urls")),
    path("ml/", include("ml_extension.urls")),
]
