"""Тесты management-команд (cron)."""

import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from notifications.models import Campaign, NotificationSchedule
from notifications.notification_api_client import NotificationApiResult

from tests.notification_admin_panel.factories import create_template, random_uuids


class ProcessCampaignsCommandTest(TestCase):
    """process_campaigns — отправка pending-кампаний."""

    @patch("notifications.services.get_notification_api_client")
    def test_processes_immediate_campaigns(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),  # UUID, не строка
            status="accepted",
            accepted_count=2,
            rejected_recipients=[],
            errors=[],
        )
        mock_get_client.return_value = mock_client

        template = create_template()
        Campaign.objects.create(
            name="Pending",
            template=template,
            delivery_channel="email",
            schedule_type="immediate",
            recipient_ids=random_uuids(2),
            last_send_status="pending",
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
            name="Already sent",
            template=template,
            delivery_channel="email",
            schedule_type="immediate",
            recipient_ids=random_uuids(1),
            last_send_status="api_accepted",
        )

        out = StringIO()
        call_command("process_campaigns", stdout=out)

        self.assertIn("Нет кампаний", out.getvalue())
        mock_client.send_notification_request.assert_not_called()


class ProcessRecurringCommandTest(TestCase):
    """process_recurring — обработка повторяющихся рассылок."""

    @patch("notifications.services.get_notification_api_client")
    def test_processes_due_schedules(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),  # UUID
            status="accepted",
            accepted_count=1,
            rejected_recipients=[],
            errors=[],
        )
        mock_get_client.return_value = mock_client

        template = create_template()
        campaign = Campaign.objects.create(
            name="Recurring",
            template=template,
            delivery_channel="email",
            schedule_type="recurring",
            cron_expression="* * * * *",
            recipient_ids=random_uuids(1),
            status="scheduled",
        )
        schedule = NotificationSchedule.objects.create(
            campaign=campaign,
            cron_expression="* * * * *",
            next_run=timezone.now() - timedelta(minutes=1),
            is_active=True,
        )

        out = StringIO()
        call_command("process_recurring", stdout=out)

        self.assertIn("Запуск recurring", out.getvalue())
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.last_run)
        self.assertGreater(schedule.next_run, timezone.now())

    @patch("notifications.services.get_notification_api_client")
    def test_skips_future_schedules(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        template = create_template()
        campaign = Campaign.objects.create(
            name="Future",
            template=template,
            delivery_channel="email",
            schedule_type="recurring",
            cron_expression="0 0 1 1 *",
            recipient_ids=random_uuids(1),
            status="scheduled",
        )
        NotificationSchedule.objects.create(
            campaign=campaign,
            cron_expression="0 0 1 1 *",
            next_run=timezone.now() + timedelta(days=365),
            is_active=True,
        )

        out = StringIO()
        call_command("process_recurring", stdout=out)

        self.assertIn("Нет повторяющихся", out.getvalue())
        mock_client.send_notification_request.assert_not_called()
