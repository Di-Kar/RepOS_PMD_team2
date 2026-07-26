"""Тесты AuthServiceBackend: вход в /admin/ через auth_service + деградация
на локальный кэш при недоступности auth_service."""
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase

from config.auth_backends import AuthServiceBackend
from config.auth_service_client import AuthServiceUnavailable, AuthServiceUser

User = get_user_model()


class AuthServiceBackendTests(TestCase):
    def setUp(self):
        self.backend = AuthServiceBackend()

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_superuser_login_grants_full_admin_access(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="1", email="root@example.com", full_name="Root Admin",
            roles=[], is_superuser=True,
        )

        user = self.backend.authenticate(None, username="root@example.com", password="pass123")

        self.assertIsNotNone(user)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("pass123"))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_admin_role_grants_access(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="2", email="manager@example.com", full_name="Content Manager",
            roles=["admin"], is_superuser=False,
        )

        user = self.backend.authenticate(None, username="manager@example.com", password="pass123")

        self.assertIsNotNone(user)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_regular_subscriber_is_denied(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="3", email="viewer@example.com", full_name="Just A Viewer",
            roles=["subscriber"], is_superuser=False,
        )

        user = self.backend.authenticate(None, username="viewer@example.com", password="pass123")

        self.assertIsNone(user)
        self.assertFalse(User.objects.filter(username="viewer@example.com").exists())

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_wrong_credentials_rejected(self, mock_auth):
        mock_auth.return_value = None  # auth_service явно отверг креды

        user = self.backend.authenticate(None, username="root@example.com", password="wrong")

        self.assertIsNone(user)

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_non_email_username_skips_network_call(self, mock_auth):
        user = self.backend.authenticate(None, username="admin", password="pass123")

        mock_auth.assert_not_called()
        self.assertIsNone(user)

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_unavailable_auth_service_without_local_cache_denies_access(self, mock_auth):
        mock_auth.side_effect = AuthServiceUnavailable("timeout")

        # Сверяем весь logs.output, не только первую строку — иначе лишняя
        # запись молча проглотится assertLogs и не будет проверена.
        with self.assertLogs("config.auth_backends", level="WARNING") as logs:
            user = self.backend.authenticate(
                None, username="unknown@example.com", password="pass123"
            )

        self.assertIsNone(user)
        self.assertEqual(
            logs.output,
            [
                "WARNING:config.auth_backends:auth_service недоступен, вход в admin_panel "
                "для unknown@example.com — в деградированном режиме"
            ],
        )

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_unavailable_auth_service_falls_back_to_local_cache(self, mock_auth):
        # Пользователь уже когда-то успешно логинился через auth_service —
        # локальное зеркало (is_staff/is_superuser + хэш пароля) существует.
        cached = User.objects.create_user(
            username="root@example.com", password="pass123", is_staff=True, is_superuser=True,
        )

        mock_auth.side_effect = AuthServiceUnavailable("connection refused")
        with self.assertLogs("config.auth_backends", level="WARNING") as logs:
            user = self.backend.authenticate(None, username="root@example.com", password="pass123")

        self.assertEqual(user, cached)
        self.assertEqual(
            logs.output,
            [
                "WARNING:config.auth_backends:auth_service недоступен, вход в admin_panel "
                "для root@example.com — в деградированном режиме"
            ],
        )

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_unavailable_auth_service_rejects_wrong_password_against_cache(self, mock_auth):
        User.objects.create_user(
            username="root@example.com", password="pass123", is_staff=True, is_superuser=True,
        )

        mock_auth.side_effect = AuthServiceUnavailable("connection refused")
        with self.assertLogs("config.auth_backends", level="WARNING") as logs:
            user = self.backend.authenticate(None, username="root@example.com", password="wrong")

        self.assertIsNone(user)
        self.assertEqual(
            logs.output,
            [
                "WARNING:config.auth_backends:auth_service недоступен, вход в admin_panel "
                "для root@example.com — в деградированном режиме"
            ],
        )

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_unavailable_auth_service_rejects_non_staff_cache(self, mock_auth):
        User.objects.create_user(
            username="viewer@example.com", password="pass123", is_staff=False,
        )

        mock_auth.side_effect = AuthServiceUnavailable("connection refused")
        with self.assertLogs("config.auth_backends", level="WARNING") as logs:
            user = self.backend.authenticate(
                None, username="viewer@example.com", password="pass123"
            )

        self.assertIsNone(user)
        self.assertEqual(
            logs.output,
            [
                "WARNING:config.auth_backends:auth_service недоступен, вход в admin_panel "
                "для viewer@example.com — в деградированном режиме"
            ],
        )


class BootstrapSuperuserLoginTests(TestCase):
    """Bootstrap-админ (username = email) должен пускать через офлайн-фолбэк,
    когда auth_service недоступен."""

    def test_bootstrap_admin_logs_in_via_degraded_fallback_when_auth_service_down(self):
        User.objects.create_superuser(
            username="admin@example.com", email="admin@example.com", password="123123",
        )

        with patch("config.auth_backends.authenticate_via_auth_service") as mock_auth:
            mock_auth.side_effect = AuthServiceUnavailable("connection refused")
            with self.assertLogs("config.auth_backends", level="WARNING") as logs:
                user = authenticate(username="admin@example.com", password="123123")

        self.assertIsNotNone(user)
        self.assertEqual(user.username, "admin@example.com")
        self.assertTrue(user.is_superuser)
        self.assertEqual(
            logs.output,
            [
                "WARNING:config.auth_backends:auth_service недоступен, вход в admin_panel "
                "для admin@example.com — в деградированном режиме"
            ],
        )
