import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from notifications.notification_api_client import NotificationApiClient, NotificationApiResult


class NotificationApiClientTest(TestCase):
    """Тесты HTTP-клиента с учётом is_temporary_error."""

    def setUp(self):
        self.client = NotificationApiClient()

    @patch("notifications.notification_api_client.requests.post")
    def test_500_error_is_temporary(self, mock_post):
        """HTTP 500 считается временной ошибкой (is_temporary_error=True)."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        result = self.client.send_notification_request(
            channel="email", recipient_ids=[str(uuid.uuid4())],
            occurred_at=timezone.now().isoformat(), template_id="1",
        )

        self.assertFalse(result.is_success)
        self.assertTrue(result.is_temporary_error)
        self.assertIn("HTTP 500", result.errors[0])

    @patch("notifications.notification_api_client.requests.post")
    def test_400_error_is_permanent(self, mock_post):
        """HTTP 400 считается постоянной ошибкой (is_temporary_error=False)."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        result = self.client.send_notification_request(
            channel="email", recipient_ids=[str(uuid.uuid4())],
            occurred_at=timezone.now().isoformat(), template_id="1",
        )

        self.assertFalse(result.is_success)
        self.assertFalse(result.is_temporary_error)

    @patch("notifications.notification_api_client.requests.post")
    def test_timeout_is_temporary(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.Timeout()

        result = self.client.send_notification_request(
            channel="email", recipient_ids=[str(uuid.uuid4())],
            occurred_at=timezone.now().isoformat(), template_id="1",
        )

        self.assertFalse(result.is_success)
        self.assertTrue(result.is_temporary_error)
        self.assertIn("Timeout", result.errors[0])

    @patch("notifications.notification_api_client.requests.post")
    def test_uses_x_api_key_header(self, mock_post):
        """Клиент использует заголовок X-API-Key, а не Bearer."""
        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "request_id": str(uuid.uuid4()), "status": "accepted",
            "accepted_count": 1, "rejected_recipients": [], "errors": [],
        }
        mock_post.return_value = mock_response

        self.client.send_notification_request(
            channel="email", recipient_ids=[str(uuid.uuid4())],
            occurred_at=timezone.now().isoformat(), template_id="1",
        )

        call_kwargs = mock_post.call_args.kwargs
        self.assertIn("X-API-Key", call_kwargs["headers"])
        self.assertEqual(call_kwargs["headers"]["X-API-Key"], self.client.api_key)
        self.assertNotIn("Authorization", call_kwargs["headers"])