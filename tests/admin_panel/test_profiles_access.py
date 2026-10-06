"""Гранулярный доступ к профилям в /admin/ (issue #112): право profiles:view из
IDM, гейт входа, синхронизация Django-права и страница профилей."""

from unittest.mock import Mock, patch

from config.auth_backends import AuthServiceBackend
from config.auth_service_client import (
    AuthServiceUnavailable,
    AuthServiceUser,
    _fetch_permissions,
)
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

VIEW_PERM = "profiles_proxy.view_profile"


def _response(status_code: int, json_body: dict | None = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


class ProfilesGateTests(TestCase):
    def setUp(self):
        self.backend = AuthServiceBackend()

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_profiles_viewer_gets_staff_without_superuser(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="10",
            email="viewer@example.com",
            full_name="Profile Viewer",
            roles=["profiles_viewer"],
            permissions=frozenset({"profiles:view"}),
        )

        user = self.backend.authenticate(
            None, username="viewer@example.com", password="pass123"
        )

        self.assertIsNotNone(user)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_perm(VIEW_PERM))
        self.assertFalse(user.has_perm("movies.change_filmwork"))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_user_without_admin_role_or_profiles_perm_is_rejected(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="11",
            email="plain@example.com",
            roles=["reader"],
            permissions=frozenset({"video:watch"}),
        )

        user = self.backend.authenticate(
            None, username="plain@example.com", password="pass123"
        )

        self.assertIsNone(user)

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_admin_role_keeps_full_access_and_no_extra_permission_needed(self, mock_auth):
        mock_auth.return_value = AuthServiceUser(
            id="12",
            email="admin@example.com",
            roles=["admin"],
            permissions=frozenset(),
        )

        user = self.backend.authenticate(
            None, username="admin@example.com", password="pass123"
        )

        self.assertTrue(user.is_superuser)
        self.assertTrue(user.has_perm("movies.change_filmwork"))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_revoked_profiles_permission_is_removed_on_next_login(self, mock_auth):
        viewer = AuthServiceUser(
            id="13",
            email="revoked@example.com",
            roles=["profiles_viewer"],
            permissions=frozenset({"profiles:view"}),
        )
        mock_auth.return_value = viewer
        self.assertTrue(
            self.backend.authenticate(
                None, username="revoked@example.com", password="pass123"
            ).has_perm(VIEW_PERM)
        )

        # Роль сняли в IDM: при следующем входе вьювер уже не пускается
        mock_auth.return_value = AuthServiceUser(
            id="13", email="revoked@example.com", roles=[], permissions=frozenset()
        )
        self.assertIsNone(
            self.backend.authenticate(
                None, username="revoked@example.com", password="pass123"
            )
        )
        user = User.objects.get(username="revoked@example.com")
        self.assertFalse(user.has_perm(VIEW_PERM))
        self.assertFalse(user.is_staff)


class DegradedAfterRevocationTests(TestCase):
    """Снятые права не должны возвращаться через degraded-вход (auth_service упал)."""

    def setUp(self):
        self.backend = AuthServiceBackend()

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_revoked_admin_cannot_login_in_degraded_mode(self, mock_auth):
        email = "former-admin@example.com"
        mock_auth.return_value = AuthServiceUser(id="20", email=email, roles=["admin"])
        self.assertIsNotNone(self.backend.authenticate(None, username=email, password="pass123"))

        # Роль admin сняли; обычный вход это фиксирует в зеркале
        mock_auth.return_value = AuthServiceUser(id="20", email=email, roles=[])
        self.assertIsNone(self.backend.authenticate(None, username=email, password="pass123"))

        # auth_service упал: degraded-вход не должен пускать снятого админа
        mock_auth.side_effect = AuthServiceUnavailable("down")
        self.assertIsNone(self.backend.authenticate(None, username=email, password="pass123"))

        user = User.objects.get(username=email)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_revoked_viewer_cannot_login_in_degraded_mode(self, mock_auth):
        email = "former-viewer@example.com"
        mock_auth.return_value = AuthServiceUser(
            id="21", email=email, roles=["profiles_viewer"],
            permissions=frozenset({"profiles:view"}),
        )
        self.assertIsNotNone(self.backend.authenticate(None, username=email, password="pass123"))

        mock_auth.return_value = AuthServiceUser(id="21", email=email, roles=[])
        self.assertIsNone(self.backend.authenticate(None, username=email, password="pass123"))

        mock_auth.side_effect = AuthServiceUnavailable("down")
        self.assertIsNone(self.backend.authenticate(None, username=email, password="pass123"))

    @patch("config.auth_backends.authenticate_via_auth_service")
    def test_degraded_mode_still_works_for_unrevoked_admin(self, mock_auth):
        """Контроль: без отзыва прав degraded-вход работает, как и раньше."""
        email = "still-admin@example.com"
        mock_auth.return_value = AuthServiceUser(id="22", email=email, roles=["admin"])
        self.assertIsNotNone(self.backend.authenticate(None, username=email, password="pass123"))

        mock_auth.side_effect = AuthServiceUnavailable("down")
        self.assertIsNotNone(self.backend.authenticate(None, username=email, password="pass123"))


class FetchPermissionsTests(TestCase):
    @patch("config.auth_service_client.requests.get")
    def test_permissions_are_taken_from_roles_matched_by_name(self, mock_get):
        mock_get.return_value = _response(
            200,
            {
                "items": [
                    {"name": "profiles_viewer", "permissions": ["profiles:view"]},
                    {"name": "reader", "permissions": ["video:watch"]},
                    {"name": "other", "permissions": ["secret:do"]},
                ],
                "total": 3,
            },
        )

        perms = _fetch_permissions("token", ["profiles_viewer", "reader"])

        self.assertEqual(perms, frozenset({"profiles:view", "video:watch"}))
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Authorization"], "Bearer token")

    @patch("config.auth_service_client.requests.get")
    def test_no_roles_means_no_idm_call(self, mock_get):
        self.assertEqual(_fetch_permissions("token", []), frozenset())
        mock_get.assert_not_called()

    @patch("config.auth_service_client.requests.get")
    def test_idm_error_fails_closed_to_empty_permissions(self, mock_get):
        mock_get.return_value = _response(500)

        self.assertEqual(_fetch_permissions("token", ["profiles_viewer"]), frozenset())

    @patch("config.auth_service_client.requests.get")
    def test_idm_network_error_fails_closed(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("down")

        self.assertEqual(_fetch_permissions("token", ["profiles_viewer"]), frozenset())


class ProfilesListViewTests(TestCase):
    def setUp(self):
        self.url = reverse("profiles_list")
        self.viewer = User.objects.create(
            username="viewer@example.com", email="viewer@example.com", is_staff=True
        )
        self.viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="profiles_proxy", codename="view_profile"
            )
        )
        self.staff_no_perm = User.objects.create(
            username="staff@example.com", email="staff@example.com", is_staff=True
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_staff_without_perm_gets_403(self):
        self.client.force_login(self.staff_no_perm)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    @patch("profiles_proxy.views.requests.get")
    def test_viewer_sees_listing_and_audit_header_is_sent(self, mock_get):
        mock_get.return_value = _response(
            200,
            {
                "items": [
                    {
                        "user_id": "550e8400-e29b-41d4-a716-446655440000",
                        "first_name": "Иван",
                        "last_name": "Петров",
                        "phone": "+79990000000",
                        "created_at": "2026-09-01T10:00:00",
                        "updated_at": "2026-09-01T10:00:00",
                    }
                ],
                "total": 1,
            },
        )
        self.client.force_login(self.viewer)

        response = self.client.get(self.url, {"search": "Иван", "page": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Петров")
        self.assertEqual(response.context["total"], 1)
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["X-Admin-Email"], "viewer@example.com")
        self.assertIn("X-Internal-Api-Key", headers)
        self.assertEqual(mock_get.call_args.kwargs["params"]["search"], "Иван")

    @patch("profiles_proxy.views.requests.get")
    def test_user_profiles_unavailable_shows_error_not_500(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("down")
        self.client.force_login(self.viewer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["error"], "Сервис профилей недоступен")

    def test_index_shows_link_only_with_permission(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, reverse("profiles_list"))

        self.client.force_login(self.staff_no_perm)
        response = self.client.get(reverse("admin:index"))
        self.assertNotContains(response, reverse("profiles_list"))
