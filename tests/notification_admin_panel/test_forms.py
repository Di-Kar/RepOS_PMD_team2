"""Тесты форм: валидация UUID, cron, расписаний."""

from django.test import TestCase
from notifications.forms import CampaignForm, MessageTemplateForm

from tests.notification_admin_panel.factories import create_template, random_uuids

# ... (остальной код тестов без изменений) ...


class MessageTemplateFormTest(TestCase):
    """Валидация шаблона в форме."""

    def test_valid_template_form_is_valid(self):
        form = MessageTemplateForm(
            data={
                "name": "Test",
                "channel": "email",
                "subject": "Hi {{ user.name }}",
                "body": "<p>{{ user.name }}</p>",
                "available_variables": '["user.name"]',
                "is_active": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_syntax_form_is_invalid(self):
        form = MessageTemplateForm(
            data={
                "name": "Bad",
                "channel": "email",
                "subject": "",
                "body": "{{ user.name",
                "available_variables": '["user.name"]',
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("body", form.errors)


class CampaignFormTest(TestCase):
    """Валидация кампании: UUID, cron, delay_hours."""

    def setUp(self):
        self.template = create_template()

    def test_valid_immediate_form(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids_raw": "\n".join(random_uuids(2)),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_recipient_ids_raw_accepts_newlines(self):
        uuids = random_uuids(3)
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids_raw": "\n".join(uuids),
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["recipient_ids_raw"], uuids)

    def test_recipient_ids_raw_accepts_json(self):
        import json

        uuids = random_uuids(2)
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids_raw": json.dumps(uuids),
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["recipient_ids_raw"], uuids)

    def test_invalid_uuid_rejected(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids_raw": "not-a-uuid",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("recipient_ids_raw", form.errors)

    def test_empty_recipients_rejected(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "immediate",
                "recipient_ids_raw": "",
            }
        )
        self.assertFalse(form.is_valid())

    def test_delayed_requires_delay_hours(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "delayed",
                "recipient_ids_raw": random_uuids(1)[0],
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("delay_hours", form.errors)

    def test_recurring_requires_cron(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "recurring",
                "recipient_ids_raw": random_uuids(1)[0],
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cron_expression", form.errors)

    def test_invalid_cron_rejected(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "recurring",
                "cron_expression": "invalid cron",
                "recipient_ids_raw": random_uuids(1)[0],
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("cron_expression", form.errors)

    def test_valid_cron_accepted(self):
        form = CampaignForm(
            data={
                "name": "Test",
                "template": self.template.pk,
                "delivery_channel": "email",
                "schedule_type": "recurring",
                "cron_expression": "0 10 * * 5",
                "recipient_ids_raw": random_uuids(1)[0],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
