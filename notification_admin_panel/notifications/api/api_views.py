"""
API Views для Notification Admin Panel.

Все эндпоинты защищены единой проверкой прав IsNotificationManager:
доступ имеют только администраторы (is_staff=True) или пользователи,
состоящие в группе 'notification_managers'.
"""

from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from notifications.models import (
    Campaign,
    MessageTemplate,
    Notification,
    NotificationSchedule,
)
from notifications.services import send_campaign_notifications
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    CampaignCreateSerializer,
    CampaignSerializer,
    CampaignUpdateSerializer,
    DashboardStatsSerializer,
    MessageTemplateCreateSerializer,
    MessageTemplateSerializer,
    MessageTemplateUpdateSerializer,
    NotificationHistorySerializer,
    NotificationSerializer,
    TemplateValidationRequestSerializer,
)

# ════════════════════════════════════════════════════════════
#  Permissions — единая проверка прав для API и HTML-панели
# ════════════════════════════════════════════════════════════


def is_notification_manager(user) -> bool:
    """
    Пользователь имеет право управлять рассылками, если:
    - он администратор (is_staff=True), ИЛИ
    - он состоит в группе 'notification_managers'.

    Эта функция используется и в DRF Permission, и в декораторе для HTML-views.
    """
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.groups.filter(name="notification_managers").exists()


class IsNotificationManager(permissions.BasePermission):
    """
    DRF Permission: доступ только для менеджеров уведомлений.
    Обычные аутентифицированные пользователи без роли получают 403.
    """

    message = (
        "У вас нет прав для управления рассылками. "
        "Требуется роль 'notification_managers' или статус администратора."
    )

    def has_permission(self, request, view) -> bool:
        return is_notification_manager(request.user)


def manager_required(view_func):
    """
    Декоратор для HTML-представлений (function-based views).
    Аналог @login_required, но с проверкой роли менеджера.

    Применение:
        @manager_required
        def campaign_create(request):
            ...
    """
    return user_passes_test(
        is_notification_manager,
        login_url="/admin/login/",
    )(view_func)


# ════════════════════════════════════════════════════════════
#  Templates (CRUD + validate)
# ════════════════════════════════════════════════════════════


class TemplateViewSet(viewsets.ModelViewSet):
    """
    CRUD шаблонов сообщений.
    GET    /api/v1/templates/          — список с фильтрацией
    POST   /api/v1/templates/          — создать (с валидацией)
    GET    /api/v1/templates/{id}/     — получить
    PUT    /api/v1/templates/{id}/     — полное обновление
    PATCH  /api/v1/templates/{id}/     — частичное обновление
    DELETE /api/v1/templates/{id}/     — удалить (с проверкой использования)
    """

    queryset = MessageTemplate.objects.all().order_by("-updated_at")
    permission_classes = [IsNotificationManager]

    def get_serializer_class(self):
        if self.action == "create":
            return MessageTemplateCreateSerializer
        if self.action in ("update", "partial_update"):
            return MessageTemplateUpdateSerializer
        return MessageTemplateSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        channel = self.request.query_params.get("channel")
        is_active = self.request.query_params.get("is_active")
        if channel:
            qs = qs.filter(channel=channel)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("true", "1"))
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Защита: нельзя удалить шаблон, используемый в активных рассылках
        active_campaigns = instance.campaigns.exclude(
            status__in=[Campaign.Status.SENT, Campaign.Status.CANCELLED]
        )
        if active_campaigns.exists():
            return Response(
                {
                    "code": "conflict",
                    "message": "Шаблон используется в активных рассылках",
                    "details": {
                        "campaign_ids": list(
                            active_campaigns.values_list("id", flat=True)
                        )
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)


class TemplateValidateView(APIView):
    """
    POST /api/v1/templates/validate/
    Предварительная валидация шаблона без сохранения в БД.
    Возвращает rendered_preview с мок-данными пользователя.
    """

    permission_classes = [IsNotificationManager]

    def post(self, request):
        serializer = TemplateValidationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        body = serializer.validated_data["body"]
        subject = serializer.validated_data.get("subject", "")

        temp_template = MessageTemplate(body=body, subject=subject)

        try:
            temp_template.validate_template()
        except DjangoValidationError as exc:
            return Response(
                {
                    "code": "validation_error",
                    "message": "Шаблон невалиден",
                    "details": {"body": exc.messages},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Рендерим превью с мок-данными
        mock_context = {
            "user": {
                "name": "Иван Иванов",
                "age": 30,
                "email": "ivan@example.com",
                "gender": "м",
                "birthday": "1993-05-15",
            }
        }
        rendered_subject, rendered_body = temp_template.render(mock_context)

        return Response(
            {
                "valid": True,
                "rendered_preview": {
                    "subject": rendered_subject,
                    "body": rendered_body,
                },
            },
            status=status.HTTP_200_OK,
        )


# ════════════════════════════════════════════════════════════
#  Campaigns (CRUD + send + notifications)
# ════════════════════════════════════════════════════════════


class CampaignViewSet(viewsets.ModelViewSet):
    """
    CRUD рассылок + действия send и notifications.
    GET    /api/v1/campaigns/
    POST   /api/v1/campaigns/
    GET    /api/v1/campaigns/{id}/
    PATCH  /api/v1/campaigns/{id}/
    DELETE /api/v1/campaigns/{id}/          — отмена рассылки
    POST   /api/v1/campaigns/{id}/send/     — немедленная отправка
    GET    /api/v1/campaigns/{id}/notifications/
    """

    queryset = Campaign.objects.select_related("template", "created_by").all()
    permission_classes = [IsNotificationManager]

    def get_serializer_class(self):
        if self.action == "create":
            return CampaignCreateSerializer
        if self.action in ("update", "partial_update"):
            return CampaignUpdateSerializer
        return CampaignSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        campaign_status = self.request.query_params.get("status")
        if campaign_status:
            qs = qs.filter(status=campaign_status)
        return qs

    def perform_create(self, serializer):
        """
        Создание кампании.
        - immediate/delayed: ставим в очередь, cron отправит в notification_api
        - recurring: создаём расписание
        """
        campaign = serializer.save(created_by=self.request.user)

        if campaign.schedule_type in (
            Campaign.ScheduleType.IMMEDIATE,
            Campaign.ScheduleType.DELAYED,
        ):
            campaign.status = Campaign.Status.SCHEDULED
            campaign.save(update_fields=["status"])

        elif campaign.schedule_type == Campaign.ScheduleType.RECURRING:
            from croniter import croniter # type: ignore[import-untyped]

            base = timezone.now()
            cron = croniter(campaign.cron_expression, base)
            next_dt = cron.get_next(timezone.datetime)
            NotificationSchedule.objects.create(
                campaign=campaign,
                cron_expression=campaign.cron_expression,
                next_run=next_dt,
                is_active=True,
            )
            campaign.status = Campaign.Status.SCHEDULED
            campaign.save(update_fields=["status"])

    def perform_destroy(self, instance):
        """Отмена рассылки: перевод в CANCELLED + отмена pending-уведомлений."""
        instance.status = Campaign.Status.CANCELLED
        instance.save(update_fields=["status"])
        instance.notifications.filter(
            status__in=[Notification.Status.PENDING, Notification.Status.SENDING]
        ).update(status=Notification.Status.FAILED)
        if hasattr(instance, "schedule"):
            instance.schedule.is_active = False
            instance.schedule.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"], url_path="send")
    def send_now(self, request, pk=None):
        """
        POST /api/v1/campaigns/{id}/send/
        Немедленная отправка кампании в notification_api.
        Использует новый request_id для каждого вызова.
        """
        campaign = self.get_object()

        if campaign.status == Campaign.Status.CANCELLED:
            return Response(
                {"error": "Cannot send cancelled campaign"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # force_new_request_id=True: каждая ручная отправка — это новый запуск
        result = send_campaign_notifications(
            campaign,
            force_new_request_id=True,
        )

        return Response(
            {
                "success": result["success"],
                "request_id": str(result.get("request_id")),
                "accepted_count": result["accepted_count"],
                "rejected_count": result.get("rejected_count", 0),
                "errors": result.get("errors", []),
            }
        )

    @action(detail=True, methods=["get"], url_path="notifications")
    def notifications(self, request, pk=None):
        """Список уведомлений конкретной рассылки."""
        campaign = self.get_object()
        qs = campaign.notifications.all().order_by("-created_at")
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = NotificationSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = NotificationSerializer(qs, many=True)
        return Response(serializer.data)


# ════════════════════════════════════════════════════════════
#  Notifications (read-only)
# ════════════════════════════════════════════════════════════


class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Только чтение уведомлений (список + детали).
    GET /api/v1/notifications/
    GET /api/v1/notifications/{notification_id}/
    """

    queryset = Notification.objects.select_related("content", "campaign").all()
    serializer_class = NotificationSerializer
    permission_classes = [IsNotificationManager]
    lookup_field = "notification_id"

    def get_queryset(self):
        qs = super().get_queryset()
        user_id = self.request.query_params.get("user_id")
        notif_status = self.request.query_params.get("status")
        channel = self.request.query_params.get("channel")
        campaign_id = self.request.query_params.get("campaign_id")

        if user_id:
            qs = qs.filter(user_id=user_id)
        if notif_status:
            qs = qs.filter(status=notif_status)
        if channel:
            qs = qs.filter(channel=channel)
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)
        return qs.order_by("-created_at")


class NotificationHistoryView(APIView):
    """
    GET /api/v1/notifications/{notification_id}/history/
    История попыток отправки конкретного уведомления.
    """

    permission_classes = [IsNotificationManager]

    def get(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            notification_id=notification_id,
        )
        history = notification.history.all().order_by("-sent_at")
        serializer = NotificationHistorySerializer(history, many=True)
        return Response(
            {
                "notification_id": str(notification.notification_id),
                "history": serializer.data,
            }
        )


# ════════════════════════════════════════════════════════════
#  Dashboard
# ════════════════════════════════════════════════════════════


class DashboardStatsView(APIView):
    """
    GET /api/v1/dashboard/
    Агрегированная статистика для главной панели.
    """

    permission_classes = [IsNotificationManager]

    def get(self, request):
        today = timezone.now().date()
        stats = {
            "templates_count": MessageTemplate.objects.filter(
                is_active=True,
            ).count(),
            "campaigns_count": Campaign.objects.count(),
            "pending_count": Notification.objects.filter(
                status=Notification.Status.PENDING,
            ).count(),
            "sent_today": Notification.objects.filter(
                status=Notification.Status.SENT,
                sent_at__date=today,
            ).count(),
        }
        serializer = DashboardStatsSerializer(stats)
        return Response(serializer.data)
