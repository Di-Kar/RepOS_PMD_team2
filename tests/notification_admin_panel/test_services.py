# notifications/tests/test_services.py

import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase
from notifications.models import CampaignSendLog
from notifications.notification_api_client import NotificationApiResult
from notifications.services import send_campaign_notifications

from tests.notification_admin_panel.factories import (
    create_campaign,
    random_uuids,
)


class SendCampaignNotificationsTest(TestCase):
    """Тесты send_campaign_notifications."""

    @patch("notifications.services.get_notification_api_client")
    def test_success_sends_to_api(self, mock_get_client):
        """Успешная отправка — создаётся лог, обновляется статус."""
        mock_client = MagicMock()
        request_id = uuid.uuid4()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=request_id,  # UUID
            status="accepted",
            accepted_count=3,
            rejected_recipients=[],
            errors=[],
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=random_uuids(3))
        result = send_campaign_notifications(campaign)

        self.assertTrue(result["success"])
        self.assertEqual(result["accepted_count"], 3)
        self.assertEqual(campaign.last_send_status, "api_accepted")
        self.assertEqual(campaign.last_send_accepted_count, 3)
        self.assertIsNotNone(campaign.last_send_at)

        log = CampaignSendLog.objects.get(campaign=campaign)
        self.assertEqual(log.accepted_count, 3)
        self.assertEqual(log.status, "accepted")
        self.assertEqual(log.request_id, request_id)  # UUID

    @patch("notifications.services.get_notification_api_client")
    def test_partial_acceptance_still_success(self, mock_get_client):
        """Частичное принятие — всё равно success."""
        mock_client = MagicMock()
        uuids = random_uuids(3)
        request_id = uuid.uuid4()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=request_id,
            status="partially_accepted",
            accepted_count=2,
            rejected_recipients=[{"user_id": uuids[0], "reason": "Invalid"}],
            errors=[],
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign(recipient_ids=uuids)
        result = send_campaign_notifications(campaign)

        self.assertTrue(result["success"])
        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["rejected_count"], 1)

    @patch("notifications.services.get_notification_api_client")
    def test_rejected_marks_campaign_as_rejected(self, mock_get_client):
        """Полный отказ — статус api_rejected."""
        mock_client = MagicMock()
        request_id = uuid.uuid4()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=request_id,
            status="rejected",
            accepted_count=0,
            rejected_recipients=[],
            errors=["template_id is required"],
        )
        mock_get_client.return_value = mock_client

        campaign = create_campaign()
        result = send_campaign_notifications(campaign)

        self.assertFalse(result["success"])
        self.assertEqual(campaign.last_send_status, "api_rejected")
        self.assertIn("template_id is required", campaign.last_send_errors)

    @patch("notifications.services.get_notification_api_client")
    def test_empty_recipients_returns_error(self, mock_get_client):
        """Пустой список получателей — не вызываем API."""
        campaign = create_campaign(recipient_ids=[])
        result = send_campaign_notifications(campaign)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No recipients")
        mock_get_client.return_value.send_notification_request.assert_not_called()

    @patch("notifications.services.get_notification_api_client")
    def test_idempotency_same_request_id(self, mock_get_client):
        """Повторный вызов использует тот же request_id."""
        mock_client = MagicMock()
        request_id = uuid.uuid4()
        mock_client.send_notification_request.return_value = NotificationApiResult(
            request_id=request_id,
            status="accepted",
            accepted_count=1,
            rejected_recipients=[],
            errors=[],
        )
        mock_get_client.return_value = mock_client

        fixed_request_id = uuid.uuid4()
        campaign = create_campaign(
            recipient_ids=random_uuids(1),
            request_id=fixed_request_id,
        )

        send_campaign_notifications(campaign)
        send_campaign_notifications(campaign)

        calls = mock_client.send_notification_request.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["request_id"], fixed_request_id)
        self.assertEqual(calls[1].kwargs["request_id"], fixed_request_id)
