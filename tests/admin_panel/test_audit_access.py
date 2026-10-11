"""Доступ к журналу аудита просмотра профилей в /admin/ (issue #117): отдельная
роль audit (audit:view в IDM), независимая от profiles_viewer, гейт входа,
синхронизация Django-права и страница аудита."""

from unittest.mock import Mock, patch

from config.auth_backends import AuthServiceBackend
from config.auth_service_client import AuthServiceUser
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

AUDIT_PERM = "profiles_proxy.view_audit"
PROFILES_PERM = "profiles_proxy.view_profile"


def _response(status_code: int, json_body: dict | None = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


class AuditGateTests(TestCase):
    def setUp(self):
        self.backend = AuthServiceBackend()

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_auditor_gets_staff_and_audit_perm_but_not_profiles_perm(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="30",
            email="auditor@example.com",
            full_name="Auditor",
            roles=["audit"],
            permissions=frozenset({"audit:view"}),
        )

        user = self.backend.authenticate(
            None, username="auditor@example.com", password="pass123"
        )

        self.assertIsNotNone(user)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_perm(AUDIT_PERM))
        self.assertFalse(user.has_perm(PROFILES_PERM))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_profiles_viewer_does_not_get_audit_perm(self, mock_auth):
        """Роли независимы: право profiles:view не даёт доступа к аудиту."""
        mock_auth.return_value = AuthServiceUser(
            id="31",
            email="viewer-only@example.com",
            roles=["profiles_viewer"],
            permissions=frozenset({"profiles:view"}),
        )

        user = self.backend.authenticate(
            None, username="viewer-only@example.com", password="pass123"
        )

        self.assertTrue(user.has_perm(PROFILES_PERM))
        self.assertFalse(user.has_perm(AUDIT_PERM))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_revoked_audit_permission_is_removed_on_next_login(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="32",
            email="revoked-auditor@example.com",
            roles=["audit"],
            permissions=frozenset({"audit:view"}),
        )
        self.assertTrue(
            self.backend.authenticate(
                None, username="revoked-auditor@example.com", password="pass123"
            ).has_perm(AUDIT_PERM)
        )

        mock_auth.return_value = AuthServiceUser(
            id="32", email="revoked-auditor@example.com", roles=[], permissions=frozenset()
        )
        self.assertIsNone(
            self.backend.authenticate(
                None, username="revoked-auditor@example.com", password="pass123"
            )
        )
        user = User.objects.get(username="revoked-auditor@example.com")
        self.assertFalse(user.has_perm(AUDIT_PERM))
        self.assertFalse(user.is_staff)


class AuditListViewTests(TestCase):
    def setUp(self):
        self.url = reverse("audit_list")
        self.auditor = User.objects.create(
            username="auditor@example.com", email="auditor@example.com", is_staff=True
        )
        self.auditor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="profiles_proxy", codename="view_audit"
            )
        )
        self.profiles_viewer_only = User.objects.create(
            username="viewer-only@example.com",
            email="viewer-only@example.com",
            is_staff=True,
        )
        self.profiles_viewer_only.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="profiles_proxy", codename="view_profile"
            )
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_profiles_viewer_without_audit_perm_gets_403(self):
        """profiles:view не даёт доступа к /admin/profiles/audit/ — роли
        независимы (см. докстринг модуля)."""
        self.client.force_login(self.profiles_viewer_only)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    @patch("profiles_proxy.views.requests.get")
    def test_auditor_sees_listing(self, mock_get):
        mock_get.return_value = _response(
            200,
            {
                "items": [
                    {
                        "admin_email": "someone@example.com",
                        "target_user_id": "550e8400-e29b-41d4-a716-446655440000",
                        "viewed_at": "2026-10-11T10:00:00",
                    }
                ],
                "total": 1,
            },
        )
        self.client.force_login(self.auditor)

        response = self.client.get(self.url, {"page": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "someone@example.com")
        self.assertEqual(response.context["total"], 1)
        self.assertIn("X-Internal-Api-Key", mock_get.call_args.kwargs["headers"])
        # В отличие от profiles_list, здесь не аудируем сам факт просмотра
        # журнала — X-Admin-Email этот запрос не отправляет.
        self.assertNotIn("X-Admin-Email", mock_get.call_args.kwargs["headers"])

    @patch("profiles_proxy.views.requests.get")
    def test_user_profiles_unavailable_shows_error_not_500(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("down")
        self.client.force_login(self.auditor)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["error"], "Сервис профилей недоступен")

    def test_index_shows_audit_link_only_with_permission(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, reverse("audit_list"))

        self.client.force_login(self.profiles_viewer_only)
        response = self.client.get(reverse("admin:index"))
        self.assertNotContains(response, reverse("audit_list"))
