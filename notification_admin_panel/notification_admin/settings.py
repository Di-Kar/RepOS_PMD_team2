import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-change-me-in-production-!@#$%"
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Сторонние
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    # Локальные
    "notifications",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # ГЛАВНОЕ: подключаем генератор схем drf-spectacular
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Notification Admin Panel API",
    "DESCRIPTION": "REST API для административной панели системы уведомлений.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Эта настройка автоматически создаст отдельные схемы для Create и Update,
    # как мы и описали в YAML (MessageTemplateCreate vs MessageTemplateUpdate)
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayOperationId": True,
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "notification_admin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "notification_admin.wsgi.application"

# ---------- DATABASE ----------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://notify_user:notify_secret@localhost:5432/notifications_db",
)
DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/panel/"
LOGOUT_REDIRECT_URL = "/admin/login/"

# ════════════════════════════════════════════════════════════
#  Notification API Client
# ════════════════════════════════════════════════════════════
NOTIFICATION_API_URL = os.environ.get(
    "NOTIFICATION_API_URL", "http://notification_api:8001/api/v1"
)
NOTIFICATION_API_KEY = os.environ.get("NOTIFICATION_API_KEY", "dev-api-key")
NOTIFICATION_API_TIMEOUT = int(os.environ.get("NOTIFICATION_API_TIMEOUT", "10"))

# Источник для аудита
NOTIFICATION_SOURCE_SERVICE = "admin_panel"
