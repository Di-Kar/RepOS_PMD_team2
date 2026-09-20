from io import StringIO
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from notifications.models import Campaign, NotificationSchedule
from notifications.notification_api_client import NotificationApiResult
from .factories import create_template, random_uuids
import uuid


class ProcessCampaignsCommandTest(TestCase):
    """Тесты management-команды process_campaigns."""

    @patch("notifications.services.get_notification_api_client")
    def test_processes_immediate_campaigns(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(), status="accepted", accepted_count=2,
            rejected_recipients=[], errors=[], is_temporary_error=False,
        )
        mock_get_client.return_value = mock_client

        template = create_template()
        Campaign.objects.create(
            name="Pending", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(2),
            last_send_status="pending", status="scheduled",
        )

        out = StringIO()
        call_command("process_campaigns", stdout=out)

        self.assertIn("Отправлено 1 кампаний", out.getvalue())
        mock_client.send_notification_request.assert_called_once()

    @patch("notifications.services.get_notification_api_client")
    def test_skips_already_sent(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        template = create_template()
        Campaign.objects.create(
            name="Already sent", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1),
            last_send_status="api_accepted", status="scheduled",
        )

        out = StringIO()
        call_command("process_campaigns", stdout=out)

        self.assertIn("Нет кампаний", out.getvalue())
        mock_client.send_notification_request.assert_not_called()


class ProcessRecurringCommandTest(TestCase):
    """Тесты management-команды process_recurring."""

    @patch("notifications.services.send_campaign_notifications")
    def test_recurring_uses_force_new_request_id(self, mock_send):
        """Проблема #3: Повторяющиеся рассылки вызывают send с force_new_request_id=True."""
        mock_send.return_value = {
            "success": True, "request_id": uuid.uuid4(), "accepted_count": 1,
            "rejected_count": 0, "errors": []
        }

        template = create_template()
        campaign = Campaign.objects.create(
            name="Recurring", template=template, delivery_channel="email",
            schedule_type="recurring", cron_expression="* * * * *",
            recipient_ids=random_uuids(1), status="scheduled",
        )
        NotificationSchedule.objects.create(
            campaign=campaign, cron_expression="* * * * *",
            next_run=timezone.now() - timedelta(minutes=1), is_active=True,
        )

        out = StringIO()
        call_command("process_recurring", stdout=out)

        self.assertIn("Запуск recurring", out.getvalue())
        # Проверяем, что функция вызвана именно с force_new_request_id=True
        mock_send.assert_called_once_with(campaign, force_new_request_id=True)