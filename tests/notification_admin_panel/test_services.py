import uuid
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from notifications.models import Campaign, CampaignSendLog
from notifications.services import send_campaign_notifications, process_pending_campaigns
from notifications.notification_api_client import NotificationApiResult
from .factories import create_campaign, create_template, random_uuids


class SendCampaignNotificationsTest(TestCase):
    """Тесты send_campaign_notifications с учётом retry и новых полей."""

    @patch("notifications.services.get_notification_api_client")
    def test_success_clears_retry_fields(self, mock_get_client):
        """Успешная отправка сбрасывает next_retry_at."""
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),
            status="accepted",
            accepted_count=3,
            rejected_recipients=[],
            errors=[],
            is_temporary_error=False,
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=random_uuids(3))
        send_campaign_notifications(campaign)

        campaign.refresh_from_db()
        self.assertEqual(campaign.last_send_status, "api_accepted")
        self.assertIsNone(campaign.next_retry_at)

    @patch("notifications.services.get_notification_api_client")
    def test_temporary_error_sets_pending_retry(self, mock_get_client):
        """Временный сбой (5xx/timeout) переводит в pending_retry и ставит next_retry_at."""
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),
            status="rejected",
            accepted_count=0,
            rejected_recipients=[],
            errors=["HTTP 500: Internal Server Error"],
            is_temporary_error=True,
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=random_uuids(3))
        send_campaign_notifications(campaign)

        campaign.refresh_from_db()
        self.assertEqual(campaign.last_send_status, "pending_retry")
        self.assertIsNotNone(campaign.next_retry_at)
        # Проверяем, что next_retry_at примерно через 5 минут
        expected_retry = timezone.now() + timedelta(minutes=5)
        self.assertAlmostEqual(
            campaign.next_retry_at.replace(microsecond=0),
            expected_retry.replace(microsecond=0),
            delta=timedelta(seconds=2)
        )

    @patch("notifications.services.get_notification_api_client")
    def test_permanent_error_sets_api_rejected(self, mock_get_client):
        """Постоянная ошибка (4xx) переводит в api_rejected, next_retry_at = None."""
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),
            status="rejected",
            accepted_count=0,
            rejected_recipients=[],
            errors=["HTTP 400: Bad Request"],
            is_temporary_error=False,
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=random_uuids(3))
        send_campaign_notifications(campaign)

        campaign.refresh_from_db()
        self.assertEqual(campaign.last_send_status, "api_rejected")
        self.assertIsNone(campaign.next_retry_at)

    @patch("notifications.services.get_notification_api_client")
    def test_retry_uses_same_current_run_request_id(self, mock_get_client):
        """При retry (force_new_request_id=False) используется тот же request_id."""
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(),
            status="accepted",
            accepted_count=1,
            rejected_recipients=[],
            errors=[],
            is_temporary_error=False,
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=random_uuids(1))
        
        # Первый вызов (инициализирует current_run_request_id, если его нет)
        send_campaign_notifications(campaign, force_new_request_id=False)
        
        # Перезагружаем кампанию из БД, чтобы получить обновлённое поле
        campaign.refresh_from_db()
        
        first_call_request_id = mock_client.send_notification_request.call_args_list[0].kwargs["request_id"]
        
        # Второй вызов (retry)
        send_campaign_notifications(campaign, force_new_request_id=False)
        second_call_request_id = mock_client.send_notification_request.call_args_list[1].kwargs["request_id"]

        self.assertEqual(first_call_request_id, second_call_request_id)
        self.assertEqual(first_call_request_id, campaign.current_run_request_id)


class ProcessPendingCampaignsTest(TestCase):
    """Тесты фоновой команды process_pending_campaigns."""

    @patch("notifications.services.get_notification_api_client")
    def test_processes_pending_and_pending_retry(self, mock_get_client):
        """Команда обрабатывает 'pending' и 'pending_retry' с наступившим временем."""
        mock_client = MagicMock()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=uuid.uuid4(), status="accepted", accepted_count=1,
            rejected_recipients=[], errors=[], is_temporary_error=False,
        )
        mock_get_client.return_value = mock_client

        template = create_template()
        
        # Кампания 1: обычный pending
        Campaign.objects.create(
            name="Pending", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1),
            last_send_status="pending", status="scheduled",
        )
        # Кампания 2: pending_retry с прошедшим временем
        Campaign.objects.create(
            name="Retry Due", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1),
            last_send_status="pending_retry", 
            next_retry_at=timezone.now() - timedelta(minutes=10),
            status="scheduled",
        )
        # Кампания 3: pending_retry с будущим временем (не должна обработаться)
        Campaign.objects.create(
            name="Retry Future", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1),
            last_send_status="pending_retry", 
            next_retry_at=timezone.now() + timedelta(hours=1),
            status="scheduled",
        )

        count = process_pending_campaigns()
        self.assertEqual(count, 2) # Обработаны только первые две

    @patch("notifications.services.get_notification_api_client")
    def test_ignores_cancelled_campaigns(self, mock_get_client):
        """Проблема #4: Отменённые кампании игнорируются, даже если last_send_status=pending."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        template = create_template()
        Campaign.objects.create(
            name="Cancelled", template=template, delivery_channel="email",
            schedule_type="immediate", recipient_ids=random_uuids(1),
            last_send_status="pending", status="cancelled", # <-- Отменена
        )

        count = process_pending_campaigns()
        self.assertEqual(count, 0)
        mock_client.send_notification_request.assert_not_called()