"""HTTP-смоук-тесты /api/v1/auth: регистрация, вход, токены, профиль, история."""
import uuid

from .conftest import BASE_URL, PASSWORD, bearer


class TestRegister:
    async def test_register_returns_user(self, session):
        email = f"smoke_{uuid.uuid4().hex[:12]}@example.com"
        async with session.post(
            f"{BASE_URL}/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "John Doe"},
        ) as response:
            assert response.status == 201
            body = await response.json()
        assert body["email"] == email
        assert body["full_name"] == "John Doe"
        assert "id" in body and "created_at" in body

    async def test_register_duplicate_email(self, session, new_user):
        async with session.post(
            f"{BASE_URL}/auth/register",
            json={"email": new_user["email"], "password": PASSWORD},
        ) as response:
            assert response.status == 409

    async def test_register_invalid_email(self, session):
        async with session.post(
            f"{BASE_URL}/auth/register",
            json={"email": "not-an-email", "password": PASSWORD},
        ) as response:
            assert response.status == 400
            body = await response.json()
        assert body["field"] == "email"

    async def test_register_short_password(self, session):
        async with session.post(
            f"{BASE_URL}/auth/register",
            json={"email": f"smoke_{uuid.uuid4().hex[:12]}@example.com", "password": "short"},
        ) as response:
            assert response.status == 400
            body = await response.json()
        assert body["error"] == "too_short_password"


class TestLogin:
    async def test_login_returns_token_pair(self, new_user, login):
        tokens = await login(new_user)
        assert tokens["access_token"] and tokens["refresh_token"]

    async def test_login_wrong_password(self, session, new_user):
        async with session.post(
            f"{BASE_URL}/auth/login",
            json={"email": new_user["email"], "password": "WrongPass123!"},
        ) as response:
            assert response.status == 401

    async def test_login_unknown_email(self, session):
        async with session.post(
            f"{BASE_URL}/auth/login",
            json={"email": f"ghost_{uuid.uuid4().hex[:12]}@example.com", "password": PASSWORD},
        ) as response:
            assert response.status == 401


class TestTokens:
    async def test_refresh_rotates_pair(self, session, tokens):
        async with session.post(
            f"{BASE_URL}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ) as response:
            assert response.status == 200
            new_tokens = await response.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

        # Старый refresh после ротации недействителен.
        async with session.post(
            f"{BASE_URL}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ) as response:
            assert response.status == 401

    async def test_logout_kills_session(self, session, tokens):
        async with session.post(f"{BASE_URL}/auth/logout", headers=bearer(tokens)) as response:
            assert response.status == 204

        async with session.get(f"{BASE_URL}/auth/profile", headers=bearer(tokens)) as response:
            assert response.status == 401

    async def test_logout_all_keeps_current_session(self, session, new_user, login):
        tokens_other = await login(new_user)
        tokens_current = await login(new_user)

        async with session.post(
            f"{BASE_URL}/auth/logout-all", headers=bearer(tokens_current)
        ) as response:
            assert response.status == 204

        async with session.get(
            f"{BASE_URL}/auth/profile", headers=bearer(tokens_current)
        ) as response:
            assert response.status == 200
        async with session.get(
            f"{BASE_URL}/auth/profile", headers=bearer(tokens_other)
        ) as response:
            assert response.status == 401


class TestProfile:
    async def test_profile_requires_token(self, session):
        async with session.get(f"{BASE_URL}/auth/profile") as response:
            assert response.status == 401

    async def test_get_profile(self, session, new_user, tokens):
        async with session.get(f"{BASE_URL}/auth/profile", headers=bearer(tokens)) as response:
            assert response.status == 200
            body = await response.json()
        assert body["email"] == new_user["email"]

    async def test_update_full_name(self, session, tokens):
        async with session.put(
            f"{BASE_URL}/auth/profile", json={"full_name": "Jane Smith"}, headers=bearer(tokens)
        ) as response:
            assert response.status == 200
            body = await response.json()
        assert body["full_name"] == "Jane Smith"

    async def test_change_password(self, session, new_user, tokens, login):
        new_password = "NewSmokePass456!"
        async with session.post(
            f"{BASE_URL}/auth/change-password",
            json={"current_password": PASSWORD, "new_password": new_password},
            headers=bearer(tokens),
        ) as response:
            assert response.status == 200

        # Старый пароль больше не работает, новый — работает.
        async with session.post(
            f"{BASE_URL}/auth/login",
            json={"email": new_user["email"], "password": PASSWORD},
        ) as response:
            assert response.status == 401
        await login(new_user, password=new_password)


class TestHistory:
    async def test_history_records_logins(self, session, new_user, login):
        await login(new_user)
        tokens = await login(new_user)

        async with session.get(f"{BASE_URL}/auth/history", headers=bearer(tokens)) as response:
            assert response.status == 200
            body = await response.json()
        assert body["total"] >= 2
        item = body["items"][0]
        assert {"timestamp", "success", "user_agent"} <= set(item)

    async def test_history_requires_token(self, session):
        async with session.get(f"{BASE_URL}/auth/history") as response:
            assert response.status == 401
