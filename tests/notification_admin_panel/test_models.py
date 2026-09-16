"""Тесты моделей: шаблоны, кампании, уведомления."""

import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase
from notifications.models import (
    Notification,
    NotificationContent,
)

from tests.notification_admin_panel.factories import (
    create_campaign,
    create_template,
    random_uuids,
)


class MessageTemplateValidationTest(TestCase):
    """Валидация шаблонов сообщений."""

    def test_valid_template_passes(self):
        tpl = create_template(
            subject="Hi {{ user.name }}",
            body="<p>Age: {{ user.age }}</p>",
            available_variables=["user.name", "user.age"],
        )
        tpl.validate_template()  # Не должно выбрасывать

    def test_unclosed_variable_tag_raises(self):
        tpl = create_template(body="Hello {{ user.name", save=False)
        with self.assertRaises(ValidationError) as ctx:
            tpl.validate_template()
        self.assertIn("Синтаксическая ошибка", str(ctx.exception))

    def test_unclosed_block_tag_raises(self):
        tpl = create_template(body="{% if True %}Hello", save=False)
        with self.assertRaises(ValidationError) as ctx:
            tpl.validate_template()
        self.assertIn("Синтаксическая ошибка", str(ctx.exception))

    def test_whitelist_violation_raises(self):
        """Переменная не в whitelist."""
        tpl = create_template(
            body="Email: {{ user.email }}",
            available_variables=["user.name"],
            save=False,
        )
        with self.assertRaises(ValidationError) as ctx:
            tpl.validate_template()
        self.assertIn("не входит в список доступных", str(ctx.exception))

    def test_subattribute_allowed_when_parent_in_whitelist(self):
        """Если разрешён user, то user.name тоже разрешён."""
        tpl = create_template(
            body="Hi {{ user.name }}",
            available_variables=["user"],
            save=False,
        )
        tpl.validate_template()  # Не должно выбрасывать

    def test_empty_whitelist_skips_variable_check(self):
        """Пустой whitelist — проверка переменных пропускается."""
        tpl = create_template(
            body="Anything {{ whatever }}",
            available_variables=[],
            save=False,
        )
        tpl.validate_template()


class CampaignModelTest(TestCase):
    """Тесты модели Campaign."""

    def test_get_recipient_list_returns_uuids(self):
        uuids = random_uuids(3)
        campaign = create_campaign(recipient_ids=uuids)
        self.assertEqual(campaign.get_recipient_list(), uuids)

    def test_get_recipient_list_empty(self):
        campaign = create_campaign(recipient_ids=[])
        self.assertEqual(campaign.get_recipient_list(), [])


class NotificationUUIDTest(TestCase):
    """user_id хранится как UUID."""

    def test_user_id_is_uuid(self):
        template = create_template()
        content = NotificationContent.objects.create(
            template=template,
            rendered_subject="Subject",
            rendered_body="Body",
        )
        user_uuid = str(uuid.uuid4())
        notif = Notification.objects.create(
            content=content,
            user_id=user_uuid,
            channel="email",
            status="pending",
            scheduled_at="2026-09-16T10:00:00Z",
        )
        self.assertEqual(str(notif.user_id), user_uuid)
        self.assertEqual(Notification.objects.get(user_id=user_uuid), notif)
