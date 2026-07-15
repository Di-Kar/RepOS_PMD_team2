"""HTTP-смоук-тесты /api/v1/idm: доступ к ролям и проверка прав."""
import uuid

from .conftest import BASE_URL, bearer


class TestRolesAccess:
    async def test_roles_require_token(self, session):
        async with session.get(f"{BASE_URL}/idm/roles") as response:
            assert response.status == 401

    async def test_list_roles_authenticated(self, session, tokens):
        async with session.get(f"{BASE_URL}/idm/roles", headers=bearer(tokens)) as response:
            assert response.status == 200
            body = await response.json()
        assert "items" in body and "total" in body

    async def test_create_role_forbidden_for_regular_user(self, session, tokens):
        # Управление ролями доступно только суперпользователю.
        async with session.post(
            f"{BASE_URL}/idm/roles",
            json={"name": f"smoke_role_{uuid.uuid4().hex[:8]}"},
            headers=bearer(tokens),
        ) as response:
            assert response.status == 403

    async def test_assign_role_forbidden_for_regular_user(self, session, new_user, tokens):
        async with session.post(
            f"{BASE_URL}/idm/users/{new_user['id']}/roles",
            json={"role_id": str(uuid.uuid4())},
            headers=bearer(tokens),
        ) as response:
            assert response.status == 403


class TestPermissionCheck:
    async def test_check_own_permission(self, session, new_user, tokens):
        async with session.post(
            f"{BASE_URL}/idm/users/{new_user['id']}/permissions/check",
            json={"permission": "video:watch"},
            headers=bearer(tokens),
        ) as response:
            assert response.status == 200
            body = await response.json()
        # У свежего пользователя нет ролей — права нет.
        assert body["has_permission"] is False
        assert body["missing_permissions"] == ["video:watch"]

    async def test_check_other_user_forbidden(self, session, tokens):
        async with session.post(
            f"{BASE_URL}/idm/users/{uuid.uuid4()}/permissions/check",
            json={"permission": "video:watch"},
            headers=bearer(tokens),
        ) as response:
            assert response.status == 403
