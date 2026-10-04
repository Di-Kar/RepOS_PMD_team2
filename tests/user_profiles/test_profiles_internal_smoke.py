"""Смоук-тесты internal-эндпоинтов /api/v1/profiles (docs/user_profiles_contract.md
§2): доступ без JWT конечного пользователя, 404 на отсутствующий профиль,
поиск по ФИО/телефону, пагинация.

PROFILES_INTERNAL_API_KEY пуст в .env для dev/test-окружения (как и
AUTH_INTERNAL_API_KEY — см. tests/auth_service), поэтому сценарий
"неверный/отсутствующий X-Internal-Api-Key -> 401" здесь не проверяется,
как и для остальных internal-эндпоинтов проекта."""

import uuid

from .conftest import BASE_URL, bearer, make_profile_request


async def _create_profile(session, auth_user, **overrides) -> dict:
    payload = make_profile_request(**overrides)
    async with session.post(
        f"{BASE_URL}/me", json=payload, headers=bearer(auth_user["tokens"])
    ) as response:
        assert response.status == 201, await response.text()
        return await response.json()


class TestGetProfileInternal:
    async def test_get_unknown_user_returns_404(self, session):
        async with session.get(f"{BASE_URL}/{uuid.uuid4()}") as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "profile_not_found"

    async def test_get_existing_profile_without_jwt(self, session, auth_user):
        created = await _create_profile(session, auth_user)

        # Internal-роут не требует Authorization — только X-Internal-Api-Key
        # (отключён в этом окружении, см. докстринг модуля).
        async with session.get(f"{BASE_URL}/{auth_user['user_id']}") as response:
            assert response.status == 200, await response.text()
            body = await response.json()
        assert body == created


class TestListProfiles:
    async def test_search_finds_by_last_name(self, session, auth_user):
        unique_last_name = f"Уникальный{uuid.uuid4().hex[:8]}"
        await _create_profile(session, auth_user, last_name=unique_last_name)

        async with session.get(
            f"{BASE_URL}", params={"search": unique_last_name}
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()
        assert body["total"] >= 1
        assert any(
            item["user_id"] == auth_user["user_id"] for item in body["items"]
        )

    async def test_search_finds_by_phone(self, session, auth_user):
        created = await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}", params={"search": created["phone"]}
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()
        assert any(item["phone"] == created["phone"] for item in body["items"])

    async def test_search_treats_underscore_as_literal_not_wildcard(
        self, session, auth_user, new_auth_user
    ):
        """ILIKE трактует '_' как "любой один символ" — без экранирования
        поиск по имени с буквальным подчёркиванием задел бы и профиль с
        другим символом на этом месте."""
        suffix = uuid.uuid4().hex[:8]
        literal_name = f"А_Б{suffix}"
        decoy_name = f"АхБ{suffix}"  # "х" вместо "_" — не должен совпасть
        await _create_profile(session, auth_user, last_name=literal_name)
        await _create_profile(session, new_auth_user, last_name=decoy_name)

        async with session.get(
            f"{BASE_URL}", params={"search": literal_name}
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        matched_ids = {item["user_id"] for item in body["items"]}
        assert auth_user["user_id"] in matched_ids
        assert new_auth_user["user_id"] not in matched_ids

    async def test_pagination_limits_items_but_total_reflects_all_matches(
        self, session, auth_user, new_auth_user
    ):
        shared_last_name = f"Общая{uuid.uuid4().hex[:8]}"
        await _create_profile(session, auth_user, last_name=shared_last_name)
        await _create_profile(session, new_auth_user, last_name=shared_last_name)

        async with session.get(
            f"{BASE_URL}",
            params={"search": shared_last_name, "page": 1, "page_size": 1},
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()
        assert len(body["items"]) == 1
        assert body["total"] >= 2


class TestGetProfileFull:
    """GET /{user_id}/full (docs/user_profiles_contract.md §2, S11_T6):
    агрегирует профиль + закладки/оценки/рецензии из ugc_service. ugc_service
    поднят и доступен в docker-compose тестового окружения, поэтому сценарий
    его недоступности (ugc_available: false) здесь не проверяется — как и
    недоступность auth_service нигде в проекте не проверяется черным ящиком
    (см. докстринг модуля)."""

    async def test_get_unknown_user_returns_404(self, session):
        async with session.get(f"{BASE_URL}/{uuid.uuid4()}/full") as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "profile_not_found"

    async def test_get_existing_profile_without_ugc_data(self, session, auth_user):
        created = await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}/full"
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert body["profile"] == created
        assert body["ugc_available"] is True
        # Свежий пользователь auth_service не создавал ни закладок, ни
        # оценок, ни рецензий в ugc_service.
        assert body["bookmarks"] == []
        assert body["ratings"] == []
        assert body["reviews"] == []
