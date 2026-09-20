"""
Формы для HTML-панели менеджера.
"""

import json
import re
import uuid

from django import forms
from django.core.exceptions import ValidationError

from .models import Campaign, MessageTemplate  # ← ОБА импорта обязательны


# ════════════════════════════════════════════════════════════
#  Форма шаблона сообщения
# ════════════════════════════════════════════════════════════
class MessageTemplateForm(forms.ModelForm):
    """Форма создания/редактирования шаблона с валидацией."""

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
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Например: Приветственное письмо",
                }
            ),
            "channel": forms.Select(attrs={"class": "form-select"}),
            "subject": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Тема письма (для email)",
                }
            ),
            "body": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 15,
                    "placeholder": (
                        "Здравствуйте, {{ user.name }}!\n\n"
                        "Ваш возраст: {{ user.age }}\n"
                        "Email: {{ user.email }}"
                    ),
                }
            ),
            "available_variables": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": '["user.name", "user.age", "user.email"]',
                }
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_available_variables(self):
        """Парсит JSON-строку в список."""
        value = self.cleaned_data.get("available_variables")
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValidationError("Должен быть JSON-массив.")
                return parsed
            except json.JSONDecodeError:
                raise ValidationError("Невалидный JSON.")
        return value

    def clean(self):
        cleaned = super().clean()
        # Собираем экземпляр для валидации
        instance = self.instance
        for k, v in cleaned.items():
            setattr(instance, k, v)
        # Вызываем валидацию шаблона
        try:
            instance.validate_template()
        except ValidationError as exc:
            for msg in exc.messages:
                self.add_error("body", msg)
        return cleaned


# ════════════════════════════════════════════════════════════
#  Форма рассылки (кампании)
# ════════════════════════════════════════════════════════════
class CampaignForm(forms.ModelForm):
    """Форма создания рассылки менеджером."""

    recipient_ids_raw = forms.CharField(
        label="ID получателей (UUID)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Введите UUID пользователей (по одному на строку или через запятую):\n"
                    "550e8400-e29b-41d4-a716-446655440000\n"
                    "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
                ),
            }
        ),
        help_text=(
            "Поддерживаются форматы: один UUID на строку, через запятую, "
            "через пробел или валидный JSON-массив."
        ),
    )

    class Meta:
        model = Campaign
        fields = [
            "name",
            "template",
            "delivery_channel",
            "schedule_type",
            "delay_hours",
            "cron_expression",
            "recurrence_description",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Например: Пятничная подборка новинок",
                }
            ),
            "template": forms.Select(attrs={"class": "form-select"}),
            "delivery_channel": forms.Select(attrs={"class": "form-select"}),
            "schedule_type": forms.Select(attrs={"class": "form-select"}),
            "delay_hours": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "placeholder": "Например: 24",
                }
            ),
            "cron_expression": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "0 10 * * 5",
                }
            ),
            "recurrence_description": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "каждую пятницу в 10:00",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.recipient_ids:
            try:
                self.fields["recipient_ids_raw"].initial = "\n".join(
                    str(uid) for uid in self.instance.recipient_ids
                )
            except (TypeError, ValueError):
                pass

    def clean_recipient_ids_raw(self) -> list[str]:
        """
        Парсит текстовый ввод и возвращает список валидных UUID-строк.
        Поддерживает: JSON-массив, по одному на строку, через запятую/пробел.
        """
        raw = self.cleaned_data.get("recipient_ids_raw", "").strip()
        if not raw:
            raise ValidationError("Необходимо указать хотя бы одного получателя.")

        candidates = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                candidates = [str(x).strip() for x in parsed if str(x).strip()]
            else:
                candidates = [str(parsed).strip()]
        except (json.JSONDecodeError, ValueError):
            candidates = [x.strip() for x in re.split(r"[,\s\n]+", raw) if x.strip()]

        if not candidates:
            raise ValidationError("Список получателей пуст.")

        valid_uuids = []
        invalid = []
        for candidate in candidates:
            try:
                uuid.UUID(candidate)
                valid_uuids.append(candidate)
            except (ValueError, AttributeError):
                invalid.append(candidate)

        if invalid:
            preview = ", ".join(invalid[:3])
            if len(invalid) > 3:
                preview += f" и ещё {len(invalid) - 3}"
            raise ValidationError(
                f"Найдены невалидные UUID ({len(invalid)} шт.): {preview}. "
                "Проверьте формат (пример: 550e8400-e29b-41d4-a716-446655440000)."
            )

        seen = set()
        unique_uuids = []
        for u in valid_uuids:
            if u not in seen:
                seen.add(u)
                unique_uuids.append(u)

        return unique_uuids

    def clean_delay_hours(self):
        """Валидация delay_hours только для delayed schedule."""
        delay_hours = self.cleaned_data.get("delay_hours")
        schedule_type = self.cleaned_data.get("schedule_type")

        if schedule_type == Campaign.ScheduleType.DELAYED:
            if not delay_hours or delay_hours < 1:
                raise ValidationError(
                    "Для отложенной рассылки укажите задержку (минимум 1 час)."
                )

        return delay_hours

    def clean_cron_expression(self):
        """Валидация cron_expression только для recurring schedule."""
        cron_expression = self.cleaned_data.get("cron_expression", "").strip()
        schedule_type = self.cleaned_data.get("schedule_type")

        if schedule_type == Campaign.ScheduleType.RECURRING:
            if not cron_expression:
                raise ValidationError(
                    "Для повторяющейся рассылки необходимо указать cron-выражение."
                )
            try:
                from croniter import croniter    # type: ignore[import-untyped]

                croniter(cron_expression)
            except (KeyError, ValueError) as exc:
                raise ValidationError(f"Некорректное cron-выражение: {exc}")

        return cron_expression

    def clean(self):
        cleaned_data = super().clean()
        # Общая логика (если нужно) может быть здесь
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.recipient_ids = self.cleaned_data.get("recipient_ids_raw", [])
        if commit:
            instance.save()
            self.save_m2m()
        return instance
