"""Смоук-тесты self-service /api/v1/profiles/me (docs/user_profiles_contract.md
§1): создание/чтение/обновление/удаление своего профиля, 401 без валидного
токена, 409 на дубликаты, 404 на отсутствующий профиль, жёсткое удаление."""

import uuid

from .conftest import BASE_URL, bearer, make_profile_request


class TestMeRequiresAuth:
    async def test_get_me_without_token_returns_401(self, session):
        async with session.get(f"{BASE_URL}/me") as response:
            assert response.status == 401

    async def test_get_me_with_garbage_token_returns_401(self, session):
        headers = {"Authorization": "Bearer not-a-real-token"}
        async with session.get(f"{BASE_URL}/me", headers=headers) as response:
            assert response.status == 401

    async def test_post_me_without_token_returns_401(self, session):
        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request()
        ) as response:
            assert response.status == 401


class TestCreateProfile:
    async def test_create_then_get_profile(self, session, auth_user):
        payload = make_profile_request()
        async with session.post(
            f"{BASE_URL}/me", json=payload, headers=bearer(auth_user["tokens"])
        ) as response:
            assert response.status == 201, await response.text()
            created = await response.json()
        assert created["user_id"] == auth_user["user_id"]
        assert created["first_name"] == payload["first_name"]
        assert created["phone"] == payload["phone"]
        assert "created_at" in created and "updated_at" in created

        async with session.get(
            f"{BASE_URL}/me", headers=bearer(auth_user["tokens"])
        ) as response:
            assert response.status == 200
            fetched = await response.json()
        assert fetched == created

    async def test_create_duplicate_returns_409(self, session, auth_user):
        headers = bearer(auth_user["tokens"])
        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request(), headers=headers
        ) as response:
            assert response.status == 201, await response.text()

        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request(), headers=headers
        ) as response:
            assert response.status == 409
            body = await response.json()
        assert body["detail"]["error"] == "profile_already_exists"

    async def test_create_with_taken_phone_returns_409(
        self, session, auth_user, new_auth_user
    ):
        payload = make_profile_request()
        async with session.post(
            f"{BASE_URL}/me", json=payload, headers=bearer(auth_user["tokens"])
        ) as response:
            assert response.status == 201, await response.text()

        async with session.post(
            f"{BASE_URL}/me",
            json=make_profile_request(phone=payload["phone"]),
            headers=bearer(new_auth_user["tokens"]),
        ) as response:
            assert response.status == 409
            body = await response.json()
        assert body["detail"]["error"] == "phone_already_taken"

    async def test_create_with_invalid_phone_returns_400(self, session, auth_user):
        async with session.post(
            f"{BASE_URL}/me",
            json=make_profile_request(phone="not-a-phone"),
            headers=bearer(auth_user["tokens"]),
        ) as response:
            assert response.status == 400, await response.text()
            body = await response.json()
        assert body["error"] == "validation_error"


class TestGetProfile:
    async def test_get_me_without_profile_returns_404(self, session, auth_user):
        async with session.get(
            f"{BASE_URL}/me", headers=bearer(auth_user["tokens"])
        ) as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "profile_not_found"


class TestUpdateProfile:
    async def test_update_without_profile_returns_404(self, session, auth_user):
        async with session.put(
            f"{BASE_URL}/me",
            json=make_profile_request(),
            headers=bearer(auth_user["tokens"]),
        ) as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "profile_not_found"

    async def test_update_profile_replaces_fields(self, session, auth_user):
        headers = bearer(auth_user["tokens"])
        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request(), headers=headers
        ) as response:
            assert response.status == 201, await response.text()

        updated_payload = make_profile_request(first_name="Пётр", last_name="Петров")
        async with session.put(
            f"{BASE_URL}/me", json=updated_payload, headers=headers
        ) as response:
            assert response.status == 200, await response.text()
            updated = await response.json()
        assert updated["first_name"] == "Пётр"
        assert updated["last_name"] == "Петров"
        assert updated["phone"] == updated_payload["phone"]

    async def test_update_to_taken_phone_returns_409(
        self, session, auth_user, new_auth_user
    ):
        taken_payload = make_profile_request()
        async with session.post(
            f"{BASE_URL}/me",
            json=taken_payload,
            headers=bearer(auth_user["tokens"]),
        ) as response:
            assert response.status == 201, await response.text()

        own_headers = bearer(new_auth_user["tokens"])
        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request(), headers=own_headers
        ) as response:
            assert response.status == 201, await response.text()

        async with session.put(
            f"{BASE_URL}/me",
            json=make_profile_request(phone=taken_payload["phone"]),
            headers=own_headers,
        ) as response:
            assert response.status == 409
            body = await response.json()
        assert body["detail"]["error"] == "phone_already_taken"


class TestDeleteProfile:
    async def test_delete_without_profile_returns_404(self, session, auth_user):
        async with session.delete(
            f"{BASE_URL}/me", headers=bearer(auth_user["tokens"])
        ) as response:
            assert response.status == 404

    async def test_delete_then_get_returns_404_and_is_not_idempotent(
        self, session, auth_user, db_conn
    ):
        headers = bearer(auth_user["tokens"])
        async with session.post(
            f"{BASE_URL}/me", json=make_profile_request(), headers=headers
        ) as response:
            assert response.status == 201, await response.text()

        async with session.delete(f"{BASE_URL}/me", headers=headers) as response:
            assert response.status == 204

        async with session.get(f"{BASE_URL}/me", headers=headers) as response:
            assert response.status == 404

        # Жёсткое удаление (FR1.5, "право на забвение") — строки физически
        # нет в БД, не просто скрыта флагом/API; проверяем это напрямую, а не
        # только через 404 от API.
        row = await db_conn.fetchrow(
            "SELECT 1 FROM profiles WHERE user_id = $1", uuid.UUID(auth_user["user_id"])
        )
        assert row is None

        # Повторный DELETE уже отсутствующего профиля — тоже 404, не 204
        # (контракт §1: здесь нет сценария ретраев, за которым стоило бы
        # прятать разницу).
        async with session.delete(f"{BASE_URL}/me", headers=headers) as response:
            assert response.status == 404
