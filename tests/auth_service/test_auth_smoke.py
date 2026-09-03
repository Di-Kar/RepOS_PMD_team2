"""HTTP-смоук-тесты /api/v1/auth: регистрация, вход, токены, профиль, история."""

import uuid

from .conftest import BASE_URL, PASSWORD, bearer, post_json


class TestRegister:
    async def test_register_returns_user(self, session):
        email = f"smoke_{uuid.uuid4().hex[:12]}@example.com"
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {"email": email, "password": PASSWORD, "full_name": "John Doe"},
        )
        assert status == 201, body
        assert body["email"] == email
        assert body["full_name"] == "John Doe"
        assert "id" in body and "created_at" in body

    async def test_register_duplicate_email(self, session, shared_user):
        status, _ = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {"email": shared_user["email"], "password": PASSWORD},
        )
        assert status == 409

    async def test_register_invalid_email(self, session):
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {"email": "not-an-email", "password": PASSWORD},
        )
        assert status == 400, body
        assert body["field"] == "email"

    async def test_register_short_password(self, session):
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {
                "email": f"smoke_{uuid.uuid4().hex[:12]}@example.com",
                "password": "short",
            },
        )
        assert status == 400, body
        assert body["error"] == "too_short_password"


class TestLogin:
    async def test_login_returns_token_pair(self, shared_user, login):
        tokens = await login(shared_user)
        assert tokens["access_token"] and tokens["refresh_token"]

    async def test_login_wrong_password(self, session, shared_user):
        status, _ = await post_json(
            session,
            f"{BASE_URL}/auth/login",
            {"email": shared_user["email"], "password": "WrongPass123!"},
        )
        assert status == 401

    async def test_login_unknown_email(self, session):
        status, _ = await post_json(
            session,
            f"{BASE_URL}/auth/login",
            {
                "email": f"ghost_{uuid.uuid4().hex[:12]}@example.com",
                "password": PASSWORD,
            },
        )
        assert status == 401


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
        async with session.post(
            f"{BASE_URL}/auth/logout", headers=bearer(tokens)
        ) as response:
            assert response.status == 204

        async with session.get(
            f"{BASE_URL}/auth/profile", headers=bearer(tokens)
        ) as response:
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

    async def test_get_profile(self, session, shared_user, shared_tokens):
        async with session.get(
            f"{BASE_URL}/auth/profile", headers=bearer(shared_tokens)
        ) as response:
            assert response.status == 200
            body = await response.json()
        assert body["email"] == shared_user["email"]

    async def test_update_full_name(self, session, shared_tokens):
        async with session.put(
            f"{BASE_URL}/auth/profile",
            json={"full_name": "Jane Smith"},
            headers=bearer(shared_tokens),
        ) as response:
            assert response.status == 200
            body = await response.json()
        assert body["full_name"] == "Jane Smith"

    async def test_change_password(self, session, new_user, login):
        # Меняет пароль — нужен эксклюзивный аккаунт, shared_user не годится.
        my_tokens = await login(new_user)
        new_password = "NewSmokePass456!"
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/change-password",
            {"current_password": PASSWORD, "new_password": new_password},
            headers=bearer(my_tokens),
        )
        assert status == 200, body

        # Старый пароль больше не работает, новый — работает.
        status, _ = await post_json(
            session,
            f"{BASE_URL}/auth/login",
            {"email": new_user["email"], "password": PASSWORD},
        )
        assert status == 401
        await login(new_user, password=new_password)


class TestHistory:
    async def test_history_records_logins(self, session, shared_user, login):
        await login(shared_user)
        tokens = await login(shared_user)

        async with session.get(
            f"{BASE_URL}/auth/history", headers=bearer(tokens)
        ) as response:
            assert response.status == 200
            body = await response.json()
        assert body["total"] >= 2
        item = body["items"][0]
        assert {"timestamp", "success", "user_agent"} <= set(item)

    async def test_history_requires_token(self, session):
        async with session.get(f"{BASE_URL}/auth/history") as response:
            assert response.status == 401
