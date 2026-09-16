"""URL-маршруты REST API."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register(r"templates", api_views.TemplateViewSet, basename="template")
router.register(r"campaigns", api_views.CampaignViewSet, basename="campaign")
router.register(
    r"notifications", api_views.NotificationViewSet, basename="notification"
)

# ВАЖНО: Кастомные URL должны быть ДО router, чтобы не конфликтовать с {pk}
urlpatterns = [
    path(
        "templates/validate/",
        api_views.TemplateValidateView.as_view(),
        name="template-validate",
    ),
    path(
        "dashboard/",
        api_views.DashboardStatsView.as_view(),
        name="dashboard-stats",
    ),
    path(
        "notifications/<uuid:notification_id>/history/",
        api_views.NotificationHistoryView.as_view(),
        name="notification-history",
    ),
    # Router ПОСЛЕ кастомных URL
    path("", include(router.urls)),
]
