"""Тесты классификации ответов auth_service: "сервис жив, но отклонил
запрос" (4xx) не должно считаться "сервис недоступен" (сеть/5xx)."""
import unittest
from unittest.mock import Mock, patch

import requests
from config.auth_service_client import (
    AuthServiceUnavailable,
    _breaker,
    authenticate_via_auth_service,
)


def _response(status_code: int, json_body: dict | None = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


class AuthenticateViaAuthServiceTests(unittest.TestCase):
    def setUp(self):
        _breaker.record_success()  # сбрасываем состояние между тестами

    @patch("config.auth_service_client.requests.post")
    def test_wrong_password_returns_none_not_unavailable(self, mock_post):
        mock_post.return_value = _response(401)

        result = authenticate_via_auth_service("user@example.com", "wrong")

        self.assertIsNone(result)
        self.assertTrue(_breaker.allow_request())  # breaker не пострадал

    @patch("config.auth_service_client.requests.post")
    def test_invalid_email_format_returns_none_not_unavailable(self, mock_post):
        mock_post.return_value = _response(400)

        result = authenticate_via_auth_service("not-an-email", "123123")

        self.assertIsNone(result)
        self.assertTrue(_breaker.allow_request())

    @patch("config.auth_service_client.requests.post")
    def test_repeated_invalid_logins_do_not_open_breaker(self, mock_post):
        mock_post.return_value = _response(400)

        for _ in range(10):
            authenticate_via_auth_service("not-an-email", "123123")

        self.assertTrue(_breaker.allow_request(), "400 не должен считаться отказом auth_service")

    @patch("config.auth_service_client.requests.post")
    def test_server_error_raises_unavailable(self, mock_post):
        mock_post.return_value = _response(500)

        with self.assertRaises(AuthServiceUnavailable):
            authenticate_via_auth_service("user@example.com", "pass")

    @patch("config.auth_service_client.requests.post")
    def test_network_error_raises_unavailable(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("boom")

        with self.assertRaises(AuthServiceUnavailable):
            authenticate_via_auth_service("user@example.com", "pass")

    @patch("config.auth_service_client.requests.get")
    @patch("config.auth_service_client.requests.post")
    def test_successful_login_fetches_profile(self, mock_post, mock_get):
        mock_post.return_value = _response(200, {"access_token": "tok", "refresh_token": "r"})
        mock_get.return_value = _response(
            200,
            {"id": "1", "email": "user@example.com", "full_name": "U", "roles": ["admin"], "is_superuser": False},
        )

        result = authenticate_via_auth_service("user@example.com", "pass")

        self.assertIsNotNone(result)
        self.assertEqual(result.email, "user@example.com")
        self.assertEqual(result.roles, ["admin"])
