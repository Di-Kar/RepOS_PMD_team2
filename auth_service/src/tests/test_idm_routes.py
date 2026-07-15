import uuid

from httpx import AsyncClient

from src.models.entity import Role, User


class TestRolesEndpoints:
    async def test_create_role_requires_superuser(self, client: AsyncClient, sample_user: User):
        response = await client.post(
            "/api/v1/idm/roles",
            json={"name": "subscriber", "permissions": ["video:watch"]},
            headers={"X-User-Id": str(sample_user.id)},
        )
        assert response.status_code == 403

    async def test_create_role_without_token(self, client: AsyncClient):
        response = await client.post("/api/v1/idm/roles", json={"name": "subscriber"})
        assert response.status_code == 401

    async def test_create_role_as_superuser(self, client: AsyncClient, sample_superuser: User):
        response = await client.post(
            "/api/v1/idm/roles",
            json={"name": "subscriber", "permissions": ["video:watch"]},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "subscriber"
        assert body["permissions"] == ["video:watch"]

    async def test_create_role_duplicate_name(
        self, client: AsyncClient, sample_superuser: User, sample_role: Role
    ):
        response = await client.post(
            "/api/v1/idm/roles",
            json={"name": sample_role.name},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 400

    async def test_list_roles(self, client: AsyncClient, sample_user: User, sample_role: Role):
        response = await client.get("/api/v1/idm/roles", headers={"X-User-Id": str(sample_user.id)})
        assert response.status_code == 200
        body = response.json()
        assert any(item["id"] == str(sample_role.id) for item in body["items"])

    async def test_update_role(self, client: AsyncClient, sample_superuser: User, sample_role: Role):
        response = await client.put(
            f"/api/v1/idm/roles/{sample_role.id}",
            json={"permissions": ["video:watch", "video:watch:new"]},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 200
        assert response.json()["permissions"] == ["video:watch", "video:watch:new"]

    async def test_update_role_not_found(self, client: AsyncClient, sample_superuser: User):
        response = await client.put(
            f"/api/v1/idm/roles/{uuid.uuid4()}",
            json={"name": "whatever"},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 404

    async def test_delete_role(self, client: AsyncClient, sample_superuser: User, sample_role: Role):
        response = await client.delete(
            f"/api/v1/idm/roles/{sample_role.id}",
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 204

    async def test_delete_role_not_found(self, client: AsyncClient, sample_superuser: User):
        response = await client.delete(
            f"/api/v1/idm/roles/{uuid.uuid4()}",
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 404


class TestUserRoleAssignment:
    async def test_assign_role(
        self, client: AsyncClient, sample_superuser: User, sample_user: User, sample_role: Role
    ):
        response = await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles",
            json={"role_id": str(sample_role.id)},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(sample_role.id)

    async def test_assign_role_conflict(
        self, client: AsyncClient, sample_superuser: User, sample_user: User, sample_role: Role
    ):
        headers = {"X-User-Id": str(sample_superuser.id)}
        await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles", json={"role_id": str(sample_role.id)}, headers=headers
        )
        response = await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles", json={"role_id": str(sample_role.id)}, headers=headers
        )
        assert response.status_code == 409

    async def test_assign_role_requires_superuser(
        self, client: AsyncClient, sample_user: User, sample_role: Role
    ):
        response = await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles",
            json={"role_id": str(sample_role.id)},
            headers={"X-User-Id": str(sample_user.id)},
        )
        assert response.status_code == 403

    async def test_revoke_role(
        self, client: AsyncClient, sample_superuser: User, sample_user: User, sample_role: Role
    ):
        headers = {"X-User-Id": str(sample_superuser.id)}
        await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles", json={"role_id": str(sample_role.id)}, headers=headers
        )
        response = await client.delete(
            f"/api/v1/idm/users/{sample_user.id}/roles/{sample_role.id}", headers=headers
        )
        assert response.status_code == 204

    async def test_revoke_role_not_assigned(
        self, client: AsyncClient, sample_superuser: User, sample_user: User, sample_role: Role
    ):
        response = await client.delete(
            f"/api/v1/idm/users/{sample_user.id}/roles/{sample_role.id}",
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 404


class TestPermissionCheck:
    async def test_check_own_permission(
        self, client: AsyncClient, sample_user: User, sample_role: Role, sample_superuser: User
    ):
        headers_admin = {"X-User-Id": str(sample_superuser.id)}
        await client.post(
            f"/api/v1/idm/users/{sample_user.id}/roles",
            json={"role_id": str(sample_role.id)},
            headers=headers_admin,
        )

        response = await client.post(
            f"/api/v1/idm/users/{sample_user.id}/permissions/check",
            json={"permission": "video:watch"},
            headers={"X-User-Id": str(sample_user.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["has_permission"] is True
        assert body["missing_permissions"] == []

    async def test_check_other_user_permission_forbidden(
        self, client: AsyncClient, sample_user: User, sample_superuser: User
    ):
        other_user_id = uuid.uuid4()
        response = await client.post(
            f"/api/v1/idm/users/{other_user_id}/permissions/check",
            json={"permission": "video:watch"},
            headers={"X-User-Id": str(sample_user.id)},
        )
        assert response.status_code == 403

    async def test_superuser_can_check_other_user_permission(
        self, client: AsyncClient, sample_user: User, sample_superuser: User
    ):
        response = await client.post(
            f"/api/v1/idm/users/{sample_user.id}/permissions/check",
            json={"permission": "video:watch"},
            headers={"X-User-Id": str(sample_superuser.id)},
        )
        assert response.status_code == 200
        assert response.json()["has_permission"] is False
