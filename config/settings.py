"""AegisNet settings.

Secrets and switches come from environment variables:
  AEGISNET_SECRET_KEY   Django secret key (a random dev key is generated and
                        stored in data/.secret_key if this is not set)
  AEGISNET_DEBUG        "1" (default) or "0"
  AEGISNET_ALLOWED_HOSTS comma separated host names
  AEGISNET_DATA_DIR     where the DB, pcaps, received files and pid files live
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AEGISNET_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
for _sub in ("run", "pcaps", "received", "uploads", "ml", "ns2", "certs"):
    (DATA_DIR / _sub).mkdir(exist_ok=True)


def _secret_key() -> str:
    env = os.environ.get("AEGISNET_SECRET_KEY")
    if env:
        return env
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_urlsafe(50)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("AEGISNET_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("AEGISNET_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "monitoring",
    "communication",
    "packet_analyzer",
    "routing",
    "simulation",
    "recovery",
    "ml_extension",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page requires a login (Django >= 5.1); the login view is exempt.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.nav",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []  # lab project: demo accounts may use simple passwords
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# AegisNet specific settings
# ---------------------------------------------------------------------------
# Socket tools and capture refuse destinations outside these networks, so the
# platform cannot be used to probe or flood arbitrary external hosts.
LAB_ALLOWED_NETWORKS = ["10.10.0.0/16", "127.0.0.0/8"]
# Host-mode (no namespaces) ping target for the dashboard latency card.
HOST_PING_TARGET = os.environ.get("AEGISNET_PING_TARGET", "127.0.0.1")
