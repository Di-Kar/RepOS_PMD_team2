"""
Сериализаторы REST API для Notification Admin Panel.
"""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from notifications.models import (
    Campaign,
    MessageTemplate,
    Notification,
    NotificationHistory,
)
from rest_framework import serializers


# ════════════════════════════════════════════════════════════
#  Шаблоны сообщений
# ════════════════════════════════════════════════════════════
class MessageTemplateSerializer(serializers.ModelSerializer):
    """Read-сериализатор шаблона (для GET-запросов)."""

    class Meta:
        model = MessageTemplate
        fields = [
            "id",
            "name",
            "channel",
            "subject",
            "body",
            "available_variables",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MessageTemplateCreateSerializer(serializers.ModelSerializer):
    """Сериализатор для создания шаблона."""

    class Meta:
        model = MessageTemplate
        fields = [
            "name",
            "channel",
            "subject",
            "body",
            "available_variables",
            "is_active",
        ]

    def clean_available_variables(self):
        """Парсит JSON-строку в список (для случаев, когда приходит строка)."""
        import json

        value = self.initial_data.get("available_variables")
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise serializers.ValidationError("Должен быть JSON-массив.")
                return parsed
            except json.JSONDecodeError:
                raise serializers.ValidationError("Невалидный JSON.")
        return value

    def validate(self, attrs):
        """Валидация синтаксиса и whitelist шаблона."""
        instance = MessageTemplate(**attrs)
        try:
            instance.validate_template()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"body": exc.messages})
        return attrs


class MessageTemplateUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор для частичного обновления шаблона (PATCH/PUT)."""

    class Meta:
        model = MessageTemplate
        fields = [
            "name",
            "channel",
            "subject",
            "body",
            "available_variables",
            "is_active",
        ]

    def validate(self, attrs):
        """Валидация только если изменились поля шаблона."""
        instance = self.instance
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.validate_template()
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"body": exc.messages})
        return attrs


class TemplateValidationRequestSerializer(serializers.Serializer):
    """Запрос на предварительную валидацию шаблона."""

    body = serializers.CharField()
    subject = serializers.CharField(required=False, default="")


class TemplateValidationResponseSerializer(serializers.Serializer):
    """Ответ с результатом валидации."""

    valid = serializers.BooleanField()
    rendered_preview = serializers.DictField(
        child=serializers.CharField(),
        required=False,
    )


# ════════════════════════════════════════════════════════════
#  Рассылки (Кампании)
# ════════════════════════════════════════════════════════════
class CreatedBySerializer(serializers.Serializer):
    """Вложенный сериализатор для создателя рассылки."""

    id = serializers.IntegerField()
    username = serializers.CharField()


class CampaignSerializer(serializers.ModelSerializer):
    """Read-сериализатор кампании."""

    created_by = CreatedBySerializer(read_only=True)

    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "template_id",
            "delivery_channel",
            "schedule_type",
            "delay_hours",
            "cron_expression",
            "recurrence_description",
            "recipient_ids",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_by", "created_at", "updated_at"]


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Сериализатор создания кампании."""

    template_id = serializers.PrimaryKeyRelatedField(
        queryset=MessageTemplate.objects.all(),
        source="template",
        help_text="ID шаблона",
    )

    class Meta:
        model = Campaign
        fields = [
            "id",  # ДОБАВЛЕНО: возвращаем id после создания
            "name",
            "template_id",
            "delivery_channel",
            "schedule_type",
            "delay_hours",
            "cron_expression",
            "recurrence_description",
            "recipient_ids",
        ]
        read_only_fields = ["id"]  # ДОБАВЛЕНО

    def validate_template_id(self, value):
        if not value.is_active:
            raise serializers.ValidationError("Шаблон неактивен.")
        return value

    def validate_recipient_ids(self, value):
        if not value:
            raise serializers.ValidationError(
                "Необходимо указать хотя бы одного получателя."
            )
        invalid = []
        for uid in value:
            try:
                uuid.UUID(str(uid))
            except (ValueError, AttributeError):
                invalid.append(uid)
        if invalid:
            raise serializers.ValidationError(f"Найдены невалидные UUID: {invalid[:3]}")
        return value

    def validate(self, attrs):
        schedule_type = attrs.get("schedule_type")
        delay_hours = attrs.get("delay_hours")
        cron_expression = attrs.get("cron_expression", "").strip()

        if schedule_type == Campaign.ScheduleType.DELAYED:
            if not delay_hours or delay_hours < 1:
                raise serializers.ValidationError(
                    {
                        "delay_hours": "Для отложенной рассылки укажите задержку (минимум 1 час)."
                    }
                )

        if schedule_type == Campaign.ScheduleType.RECURRING:
            if not cron_expression:
                raise serializers.ValidationError(
                    {
                        "cron_expression": "Для повторяющейся рассылки необходимо указать cron-выражение."
                    }
                )
            try:
                from croniter import croniter

                croniter(cron_expression)
            except (KeyError, ValueError) as exc:
                raise serializers.ValidationError(
                    {"cron_expression": f"Некорректное cron-выражение: {exc}"}
                )

        return attrs


class CampaignUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор частичного обновления кампании."""

    class Meta:
        model = Campaign
        fields = [
            "name",
            "delay_hours",
            "cron_expression",
            "recurrence_description",
            "recipient_ids",
        ]

    def validate(self, attrs):
        # Нельзя редактировать отправленные/отменённые рассылки
        if self.instance.status in (
            Campaign.Status.SENT,
            Campaign.Status.CANCELLED,
        ):
            raise serializers.ValidationError(
                "Нельзя редактировать завершённую или отменённую рассылку."
            )
        return attrs


# ════════════════════════════════════════════════════════════
#  Уведомления
# ════════════════════════════════════════════════════════════
class NotificationSerializer(serializers.ModelSerializer):
    """Read-сериализатор уведомления."""

    content_id = serializers.UUIDField(source="content.content_id", read_only=True)
    campaign_id = serializers.PrimaryKeyRelatedField(
        source="campaign",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Notification
        fields = [
            "notification_id",
            "content_id",
            "campaign_id",
            "user_id",
            "channel",
            "status",
            "scheduled_at",
            "sent_at",
            "last_update",
            "last_notification_send",
            "created_at",
        ]
        read_only_fields = fields


class NotificationHistorySerializer(serializers.ModelSerializer):
    """Сериализатор истории попыток отправки."""

    class Meta:
        model = NotificationHistory
        fields = [
            "id",
            "notification_id",
            "status",
            "sent_at",
            "error_message",
            "delivery_provider",
        ]
        read_only_fields = fields


# ════════════════════════════════════════════════════════════
#  Dashboard
# ════════════════════════════════════════════════════════════
class DashboardStatsSerializer(serializers.Serializer):
    """Статистика дашборда."""

    templates_count = serializers.IntegerField()
    campaigns_count = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    sent_today = serializers.IntegerField()
