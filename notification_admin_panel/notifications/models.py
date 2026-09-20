import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.template import TemplateSyntaxError, engines


class MessageTemplate(models.Model):
    """Шаблон сообщения с поддержкой переменных {{ user.name }}."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        PUSH = "push", "Push-уведомление"

    name = models.CharField("Название шаблона", max_length=255)
    channel = models.CharField(
        "Канал доставки",
        max_length=10,
        choices=Channel.choices,
        default=Channel.EMAIL,
    )
    subject = models.CharField("Тема (email)", max_length=500, blank=True, default="")
    body = models.TextField("Тело сообщения (HTML / текст)")
    available_variables = models.JSONField(
        "Доступные переменные",
        default=list,
        blank=True,
    )
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        db_table = "message_templates"
        verbose_name = "Шаблон сообщения"
        verbose_name_plural = "Шаблоны сообщений"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"[{self.get_channel_display()}] {self.name}"

    def validate_template(self):
        """
        Полная валидация шаблона:
        1. Синтаксис Django-шаблона (включая незакрытые теги)
        2. Whitelist переменных
        3. Рендеринг с мок-данными
        """
        engine = engines["django"]

        # 1. Дополнительная проверка на незакрытые теги {{ ... }}
        open_tags = re.findall(r"\{\{(?!\}\})", self.body)
        close_tags = re.findall(r"\}\}", self.body)
        if len(open_tags) != len(close_tags):
            raise ValidationError(
                "Синтаксическая ошибка: незакрытый тег переменной {{ ... }}"
            )

        # 1b. Проверка синтаксиса через Django engine
        try:
            tpl = engine.from_string(self.body)
        except TemplateSyntaxError as exc:
            error_msg = str(exc)
            if "Unclosed" in error_msg or "unclosed" in error_msg:
                raise ValidationError(
                    f"Синтаксическая ошибка: незакрытый тег. {error_msg}"
                )
            raise ValidationError(f"Синтаксическая ошибка: {error_msg}")

        # 1c. Проверка subject
        if self.subject:
            open_tags_subject = re.findall(r"\{\{(?!\}\})", self.subject)
            close_tags_subject = re.findall(r"\}\}", self.subject)
            if len(open_tags_subject) != len(close_tags_subject):
                raise ValidationError(
                    "Синтаксическая ошибка в теме: незакрытый тег переменной"
                )

            try:
                engine.from_string(self.subject)
            except TemplateSyntaxError as exc:
                error_msg = str(exc)
                if "Unclosed" in error_msg or "unclosed" in error_msg:
                    raise ValidationError(
                        f"Синтаксическая ошибка в теме: незакрытый тег. {error_msg}"
                    )
                raise ValidationError(f"Синтаксическая ошибка в теме: {error_msg}")

        # 2. Проверка whitelist переменных
        if self.available_variables:
            used_vars = set()
            for text in [self.body, self.subject or ""]:
                used_vars.update(
                    re.findall(r"\{\{\s*([\w\.]+)\s*(?:\|[^}]*)?\}\}", text)
                )

            for var in used_vars:
                allowed = False
                for allowed_var in self.available_variables:
                    if var == allowed_var or var.startswith(allowed_var + "."):
                        allowed = True
                        break
                if not allowed:
                    raise ValidationError(
                        f"Переменная '{var}' не входит в список доступных переменных. "
                        f"Разрешены: {', '.join(self.available_variables)}"
                    )

        # 3. Рендеринг с мок-данными
        mock_context = {
            "user": {
                "name": "Тест",
                "age": 30,
                "email": "test@example.com",
                "gender": "м",
                "birthday": "1995-01-01",
            }
        }
        try:
            tpl.render(mock_context)
        except Exception as exc:
            raise ValidationError(f"Ошибка рендеринга: {exc}")

    def clean(self):
        super().clean()
        self.validate_template()

    def render(self, context: dict) -> tuple[str, str]:
        engine = engines["django"]
        rendered_body = engine.from_string(self.body).render(context)
        rendered_subject = (
            engine.from_string(self.subject).render(context) if self.subject else ""
        )
        return rendered_subject, rendered_body


class NotificationContent(models.Model):
    """Отрендеренный контент уведомления."""

    content_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contents",
    )
    rendered_subject = models.CharField(max_length=500, blank=True, default="")
    rendered_body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_contents"
        verbose_name = "Контент уведомления"
        verbose_name_plural = "Контент уведомлений"

    def __str__(self):
        return str(self.content_id)


class Campaign(models.Model):
    """Рассылка (кампания)."""

    class ScheduleType(models.TextChoices):
        IMMEDIATE = "immediate", "Немедленно"
        DELAYED = "delayed", "Отложенная"
        RECURRING = "recurring", "Повторяющаяся"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        SCHEDULED = "scheduled", "Запланирована"
        SENDING = "sending", "Отправляется"
        SENT = "sent", "Отправлена"
        CANCELLED = "cancelled", "Отменена"

    name = models.CharField("Название рассылки", max_length=255)
    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.CASCADE,
        verbose_name="Шаблон",
        related_name="campaigns",
    )
    delivery_channel = models.CharField(
        "Канал",
        max_length=10,
        choices=MessageTemplate.Channel.choices,
        default=MessageTemplate.Channel.EMAIL,
    )
    schedule_type = models.CharField(
        "Тип расписания",
        max_length=20,
        choices=ScheduleType.choices,
        default=ScheduleType.IMMEDIATE,
    )
    delay_hours = models.PositiveIntegerField(
        "Задержка (часов)",
        null=True,
        blank=True,
    )
    cron_expression = models.CharField(
        "Cron-выражение",
        max_length=100,
        blank=True,
        default="",
    )
    recurrence_description = models.CharField(
        "Описание периодичности",
        max_length=255,
        blank=True,
        default="",
    )
    recipient_ids = models.JSONField(
        "ID получателей (UUID)",
        default=list,
        blank=True,
        help_text="Массив UUID пользователей",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    
    # Базовый ID заявки (генерируется при создании кампании)
    request_id = models.UUIDField(
        "ID заявки в notification_api",
        default=uuid.uuid4,
        unique=True,
    )
    
    # --- ДОБАВЛЕНО ДЛЯ РЕШЕНИЯ ПРОБЛЕМ #3 и #5 ---
    current_run_request_id = models.UUIDField(
        "ID текущего запуска",
        null=True,
        blank=True,
        help_text="Новый UUID для каждого запуска recurring. Сохраняется при retry этого запуска.",
    )
    next_retry_at = models.DateTimeField(
        "Следующая попытка при сбое",
        null=True,
        blank=True,
        help_text="Время следующей попытки отправки при временной ошибке API (таймаут, 5xx)",
    )
    # -----------------------------------------------

    last_send_status = models.CharField(
        "Статус последней отправки",
        max_length=20,
        choices=[
            ("pending", "Ожидает отправки"),
            ("pending_retry", "Временный сбой, ожидает повторной попытки"), # <-- ДОБАВЛЕНО для Issue #5
            ("sent_to_api", "Отправлено в notification_api"),
            ("api_accepted", "Принято notification_api"),
            ("api_rejected", "Отклонено notification_api (ошибка данных)"),
            ("failed", "Ошибка отправки"),
        ],
        default="pending",
    )
    last_send_accepted_count = models.IntegerField(
        "Принято получателей",
        default=0,
    )
    last_send_at = models.DateTimeField(
        "Последняя отправка",
        null=True,
        blank=True,
    )
    last_send_errors = models.JSONField(
        "Ошибки последней отправки",
        default=list,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Менеджер",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "campaigns"
        verbose_name = "Рассылка"
        verbose_name_plural = "Рассылки"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def get_recipient_list(self) -> list[str]:
        if not self.recipient_ids:
            return []
        return [str(uid) for uid in self.recipient_ids if uid]


class NotificationSchedule(models.Model):
    """Расписание для повторяющихся рассылок."""

    campaign = models.OneToOneField(
        Campaign,
        on_delete=models.CASCADE,
        related_name="schedule",
        verbose_name="Рассылка",
    )
    cron_expression = models.CharField("Cron-выражение", max_length=100)
    next_run = models.DateTimeField("Следующий запуск", null=True, blank=True)
    last_run = models.DateTimeField("Последний запуск", null=True, blank=True)
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        db_table = "notification_schedules"
        verbose_name = "Расписание"
        verbose_name_plural = "Расписания"

    def __str__(self):
        return f"Schedule for {self.campaign} -> {self.cron_expression}"


class Notification(models.Model):
    """Индивидуальное уведомление пользователю."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        SENDING = "sending", "Отправляется"
        SENT = "sent", "Отправлено"
        FAILED = "failed", "Ошибка"
        # Добавлено по комментарию: пользователь неактивен либо канал ещё не реализован
        SKIPPED = "skipped", "Пропущено"

    notification_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    content = models.ForeignKey(
        NotificationContent,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Контент",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    user_id = models.UUIDField("ID пользователя (UUID)")
    channel = models.CharField(
        "Канал",
        max_length=10,
        choices=MessageTemplate.Channel.choices,
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    scheduled_at = models.DateTimeField("Запланировано на")
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    last_update = models.DateTimeField("Последнее обновление", auto_now=True)
    last_notification_send = models.DateTimeField(
        "Последняя попытка отправки",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "scheduled_at"],
                name="idx_notif_status_sched",
                condition=models.Q(status="pending"),
            ),
            models.Index(fields=["user_id"], name="idx_notif_user_id"),
        ]

    def __str__(self):
        return f"{self.notification_id} -> user {self.user_id} [{self.status}]"


class NotificationHistory(models.Model):
    """История попыток отправки уведомления."""

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="history",
        verbose_name="Уведомление",
    )
    status = models.CharField("Статус", max_length=20)
    sent_at = models.DateTimeField("Время", auto_now_add=True)
    error_message = models.TextField("Ошибка", blank=True, default="")
    delivery_provider = models.CharField(
        "Провайдер",
        max_length=50,
        blank=True,
        default="",
    )

    class Meta:
        db_table = "notification_history"
        verbose_name = "Запись истории"
        verbose_name_plural = "История отправок"
        ordering = ["-sent_at"]

    def __str__(self):
        # ИСПРАВЛЕНО: используем self.notification.notification_id, так как прямого поля notification_id в этой модели нет
        return f"{self.notification.notification_id} @ {self.sent_at} -> {self.status}"


class CampaignSendLog(models.Model):
    """Лог каждой отправки заявки в notification_api."""

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="send_logs",
    )
    request_id = models.UUIDField("ID заявки")
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField("Статус", max_length=20)
    accepted_count = models.IntegerField("Принято получателей")
    rejected_count = models.IntegerField("Отклонено получателей", default=0)
    errors = models.JSONField("Ошибки", default=list)

    class Meta:
        db_table = "campaign_send_logs"
        verbose_name = "Лог отправки"
        verbose_name_plural = "Логи отправок"
        ordering = ["-sent_at"]

    def __str__(self):
        return f"Campaign {self.campaign_id} @ {self.sent_at} -> {self.status}"