"""Интеграционные тесты роутов /api/v1/auth (по openapi_auth.yaml)."""
from httpx import AsyncClient

from src.models.entity import User

PASSWORD = "SecurePass123!"


async def _login(client: AsyncClient, user: User, password: str = PASSWORD) -> dict:
    """Логинится и возвращает пару токенов."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.login, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestRegister:
    async def test_register_success(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "new.user@example.com", "password": PASSWORD, "full_name": "John Doe"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "new.user@example.com"
        assert body["full_name"] == "John Doe"
        assert "id" in body and "created_at" in body

    async def test_register_email_taken(self, client: AsyncClient, registered_user: User):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": registered_user.login, "password": PASSWORD},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "email_taken"

    async def test_register_invalid_email(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD}
        )
        assert response.status_code == 400
        assert response.json()["field"] == "email"

    async def test_register_too_short_password(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register", json={"email": "a@b.com", "password": "short"}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"] == "too_short_password"
        assert body["field"] == "password"

    async def test_register_missing_password(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json={"email": "a@b.com"})
        assert response.status_code == 400
        assert response.json()["error"] == "missing_password"

    async def test_registered_user_can_login(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register", json={"email": "flow@example.com", "password": PASSWORD}
        )
        response = await client.post(
            "/api/v1/auth/login", json={"email": "flow@example.com", "password": PASSWORD}
        )
        assert response.status_code == 200


class TestLogin:
    async def test_login_success(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        assert tokens["access_token"] and tokens["refresh_token"]

    async def test_login_wrong_password(self, client: AsyncClient, registered_user: User):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user.login, "password": "WrongPass123!"},
        )
        assert response.status_code == 401

    async def test_login_unknown_email(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
        )
        assert response.status_code == 401

    async def test_failed_login_recorded_in_history(
        self, client: AsyncClient, registered_user: User
    ):
        await client.post(
            "/api/v1/auth/login",
            json={"email": registered_user.login, "password": "WrongPass123!"},
        )
        tokens = await _login(client, registered_user)

        response = await client.get("/api/v1/auth/history", headers=_bearer(tokens))
        assert response.status_code == 200
        successes = [item["success"] for item in response.json()["items"]]
        assert False in successes and True in successes


class TestRefresh:
    async def test_refresh_returns_new_pair(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert response.status_code == 200
        new_tokens = response.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]
        # Новый access-токен рабочий.
        profile = await client.get("/api/v1/auth/profile", headers=_bearer(new_tokens))
        assert profile.status_code == 200

    async def test_refresh_rotation_invalidates_old_token(
        self, client: AsyncClient, registered_user: User
    ):
        tokens = await _login(client, registered_user)
        await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        # Повторное использование уже ротированного refresh — 401.
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert response.status_code == 401

    async def test_refresh_with_access_token_fails(
        self, client: AsyncClient, registered_user: User
    ):
        tokens = await _login(client, registered_user)
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
        )
        assert response.status_code == 401

    async def test_refresh_with_garbage_fails(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        assert response.status_code == 401


class TestLogout:
    async def test_logout_kills_session(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.post("/api/v1/auth/logout", headers=_bearer(tokens))
        assert response.status_code == 204

        # Access-токен завершённой сессии больше не работает.
        profile = await client.get("/api/v1/auth/profile", headers=_bearer(tokens))
        assert profile.status_code == 401
        # И refresh тоже.
        refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh.status_code == 401

    async def test_logout_without_token(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 401

    async def test_logout_all_keeps_current_session(
        self, client: AsyncClient, registered_user: User
    ):
        tokens_device1 = await _login(client, registered_user)
        tokens_device2 = await _login(client, registered_user)

        response = await client.post("/api/v1/auth/logout-all", headers=_bearer(tokens_device1))
        assert response.status_code == 204

        # Текущая сессия жива, остальные завершены.
        assert (
            await client.get("/api/v1/auth/profile", headers=_bearer(tokens_device1))
        ).status_code == 200
        assert (
            await client.get("/api/v1/auth/profile", headers=_bearer(tokens_device2))
        ).status_code == 401


class TestProfile:
    async def test_get_profile(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.get("/api/v1/auth/profile", headers=_bearer(tokens))
        assert response.status_code == 200
        body = response.json()
        assert body["email"] == registered_user.login
        assert body["full_name"] == "John Doe"

    async def test_get_profile_without_token(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/profile")
        assert response.status_code == 401

    async def test_get_profile_with_garbage_token(self, client: AsyncClient):
        response = await client.get(
            "/api/v1/auth/profile", headers={"Authorization": "Bearer garbage"}
        )
        assert response.status_code == 401

    async def test_update_full_name(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.put(
            "/api/v1/auth/profile", json={"full_name": "Jane Q. Smith"}, headers=_bearer(tokens)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["full_name"] == "Jane Q. Smith"
        # Email не изменился.
        assert body["email"] == registered_user.login


class TestChangePassword:
    async def test_change_password_success(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "NewSecurePass456!"},
            headers=_bearer(tokens),
        )
        assert response.status_code == 200

        # Старый пароль больше не подходит, новый — работает.
        old = await client.post(
            "/api/v1/auth/login", json={"email": registered_user.login, "password": PASSWORD}
        )
        assert old.status_code == 401
        await _login(client, registered_user, password="NewSecurePass456!")

    async def test_change_password_wrong_current(
        self, client: AsyncClient, registered_user: User
    ):
        tokens = await _login(client, registered_user)
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "WrongPass!", "new_password": "NewSecurePass456!"},
            headers=_bearer(tokens),
        )
        assert response.status_code == 400

    async def test_change_password_revokes_other_sessions(
        self, client: AsyncClient, registered_user: User
    ):
        tokens_other = await _login(client, registered_user)
        tokens_current = await _login(client, registered_user)

        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "NewSecurePass456!"},
            headers=_bearer(tokens_current),
        )
        assert response.status_code == 200

        assert (
            await client.get("/api/v1/auth/profile", headers=_bearer(tokens_current))
        ).status_code == 200
        assert (
            await client.get("/api/v1/auth/profile", headers=_bearer(tokens_other))
        ).status_code == 401


class TestHistory:
    async def test_history_pagination(self, client: AsyncClient, registered_user: User):
        # Три входа — три записи в истории.
        for _ in range(3):
            tokens = await _login(client, registered_user)

        response = await client.get(
            "/api/v1/auth/history", params={"page": 1, "size": 2}, headers=_bearer(tokens)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["page"] == 1 and body["size"] == 2
        assert len(body["items"]) == 2

        second_page = await client.get(
            "/api/v1/auth/history", params={"page": 2, "size": 2}, headers=_bearer(tokens)
        )
        assert len(second_page.json()["items"]) == 1

    async def test_history_item_shape(self, client: AsyncClient, registered_user: User):
        tokens = await _login(client, registered_user)
        response = await client.get("/api/v1/auth/history", headers=_bearer(tokens))
        item = response.json()["items"][0]
        assert {"id", "user_agent", "ip_address", "fingerprint", "timestamp", "success"} <= set(item)

    async def test_history_without_token(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/history")
        assert response.status_code == 401
