# notifications/tests/test_notification_api_client.py (фрагмент)

import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from notifications.notification_api_client import (
    NotificationApiClient,
)


class NotificationApiClientTest(TestCase):
    """Тесты HTTP-клиента."""

    def setUp(self):
        self.client = NotificationApiClient()

    @patch("notifications.notification_api_client.requests.post")
    def test_success_accepted(self, mock_post):
        """Все получатели приняты."""
        request_id = uuid.uuid4()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "request_id": str(request_id),  # Строка в JSON
            "status": "accepted",
            "accepted_count": 2,
            "rejected_recipients": [],
            "errors": [],
        }
        mock_post.return_value = mock_response

        result = self.client.send_notification_request(
            channel="email",
            recipient_ids=[str(uuid.uuid4()) for _ in range(2)],
            occurred_at=timezone.now().isoformat(),
            template_id="1",
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.accepted_count, 2)
        self.assertEqual(result.request_id, request_id)  # UUID

    @patch("notifications.notification_api_client.requests.post")
    def test_partial_acceptance(self, mock_post):
        """Часть получателей отклонена."""
        request_id = uuid.uuid4()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "request_id": str(request_id),
            "status": "partially_accepted",
            "accepted_count": 1,
            "rejected_recipients": [{"user_id": "bad-uuid", "reason": "Invalid UUID"}],
            "errors": [],
        }
        mock_post.return_value = mock_response

        result = self.client.send_notification_request(
            channel="email",
            recipient_ids=[str(uuid.uuid4()), "bad-uuid"],
            occurred_at=timezone.now().isoformat(),
            template_id="1",
        )

        self.assertTrue(result.is_success)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(len(result.rejected_recipients), 1)

    @patch("notifications.notification_api_client.requests.post")
    def test_rejected_returns_failed_result(self, mock_post):
        """Заявка отклонена целиком."""
        request_id = uuid.uuid4()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "request_id": str(request_id),
            "status": "rejected",
            "accepted_count": 0,
            "rejected_recipients": [],
            "errors": ["template_id is required"],
        }
        mock_post.return_value = mock_response

        result = self.client.send_notification_request(
            channel="email",
            recipient_ids=[str(uuid.uuid4())],
            occurred_at=timezone.now().isoformat(),
        )

        self.assertFalse(result.is_success)
        self.assertEqual(result.status, "rejected")

    @patch("notifications.notification_api_client.requests.post")
    def test_payload_structure(self, mock_post):
        """Проверяем, что payload корректно формируется."""
        request_id = uuid.uuid4()
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "request_id": str(request_id),
            "status": "accepted",
            "accepted_count": 1,
            "rejected_recipients": [],
            "errors": [],
        }
        mock_post.return_value = mock_response

        user_uuid = str(uuid.uuid4())

        self.client.send_notification_request(
            channel="email",
            recipient_ids=[user_uuid],
            occurred_at="2026-09-16T10:00:00Z",
            template_id="7",
            campaign_id="42",
            context={"movie_title": "Matrix"},
            request_id=request_id,
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]

        self.assertEqual(payload["request_id"], str(request_id))  # Строка в JSON
        self.assertEqual(payload["source_service"], "admin_panel")
        self.assertEqual(payload["channel"], "email")
        self.assertEqual(payload["recipient_ids"], [user_uuid])
        self.assertEqual(payload["template_id"], "7")
        self.assertEqual(payload["campaign_id"], "42")
        self.assertEqual(payload["context"], {"movie_title": "Matrix"})
        self.assertEqual(payload["occurred_at"], "2026-09-16T10:00:00Z")
