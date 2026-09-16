from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # Django Admin (для разработчиков)
    path("admin/", admin.site.urls),
    # HTML-панель для менеджеров (session auth + шаблоны)
    path("panel/", include("notifications.urls")),
    # REST API: аутентификация
    path("api/v1/auth/login/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # REST API: бизнес-логика (JWT auth + DRF viewsets)
    path("api/v1/", include("notifications.api.api_urls")),
    # OpenAPI документация
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
