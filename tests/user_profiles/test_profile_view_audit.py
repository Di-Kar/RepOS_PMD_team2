"""Тесты аудита просмотра профиля администратором (docs/user_profiles_contract.md
§3, S11_T10, issue #117): заголовок X-Admin-Email на internal-эндпоинтах
пишет строку в profile_view_audit, его отсутствие — не пишет ничего."""

import uuid

from .conftest import BASE_URL, bearer, make_profile_request

ADMIN_EMAIL = "admin@example.com"


async def _create_profile(session, auth_user, **overrides) -> dict:
    payload = make_profile_request(**overrides)
    async with session.post(
        f"{BASE_URL}/me", json=payload, headers=bearer(auth_user["tokens"])
    ) as response:
        assert response.status == 201, await response.text()
        return await response.json()


async def _audit_rows(db_conn, target_user_id: str) -> list:
    rows = await db_conn.fetch(
        "SELECT admin_email, target_user_id, viewed_at FROM profile_view_audit "
        "WHERE target_user_id = $1",
        uuid.UUID(target_user_id),
    )
    return rows


class TestAuditOnGetProfile:
    async def test_header_present_writes_audit_row(self, session, auth_user, db_conn):
        await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()

        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert len(rows) == 1
        assert rows[0]["admin_email"] == ADMIN_EMAIL

    async def test_header_absent_writes_nothing(self, session, auth_user, db_conn):
        await _create_profile(session, auth_user)

        async with session.get(f"{BASE_URL}/{auth_user['user_id']}") as response:
            assert response.status == 200, await response.text()

        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert rows == []

    async def test_404_does_not_write_audit(self, session, db_conn):
        unknown_id = str(uuid.uuid4())

        async with session.get(
            f"{BASE_URL}/{unknown_id}",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 404

        rows = await _audit_rows(db_conn, unknown_id)
        assert rows == []


class TestAuditOnGetProfileFull:
    async def test_header_present_writes_audit_row(self, session, auth_user, db_conn):
        await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}/full",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()

        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert len(rows) == 1


class TestAuditOnListProfiles:
    async def test_header_present_writes_one_row_per_item_on_page(
        self, session, auth_user, new_auth_user, db_conn
    ):
        shared_last_name = f"Аудит{uuid.uuid4().hex[:8]}"
        await _create_profile(session, auth_user, last_name=shared_last_name)
        await _create_profile(session, new_auth_user, last_name=shared_last_name)

        async with session.get(
            BASE_URL,
            params={"search": shared_last_name},
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()

        rows_a = await _audit_rows(db_conn, auth_user["user_id"])
        rows_b = await _audit_rows(db_conn, new_auth_user["user_id"])
        assert len(rows_a) == 1
        assert len(rows_b) == 1

    async def test_header_absent_writes_nothing(self, session, auth_user, db_conn):
        unique_last_name = f"БезАудита{uuid.uuid4().hex[:8]}"
        await _create_profile(session, auth_user, last_name=unique_last_name)

        async with session.get(
            BASE_URL, params={"search": unique_last_name}
        ) as response:
            assert response.status == 200, await response.text()

        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert rows == []

    async def test_items_on_same_page_are_committed_together(
        self, session, auth_user, new_auth_user, db_conn
    ):
        """issue #134: один commit на всю страницу — Postgres now() фиксирован
        на старте транзакции, поэтому у обеих строк одинаковый viewed_at.
        До фикса (раздельные commit на каждый профиль) значения почти
        гарантированно различаются — сетевой round-trip между commit'ами
        не укладывается в разрешение timestamp."""
        shared_last_name = f"Пакет{uuid.uuid4().hex[:8]}"
        await _create_profile(session, auth_user, last_name=shared_last_name)
        await _create_profile(session, new_auth_user, last_name=shared_last_name)

        async with session.get(
            BASE_URL,
            params={"search": shared_last_name},
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()

        rows_a = await _audit_rows(db_conn, auth_user["user_id"])
        rows_b = await _audit_rows(db_conn, new_auth_user["user_id"])
        assert len(rows_a) == 1
        assert len(rows_b) == 1
        assert rows_a[0]["viewed_at"] == rows_b[0]["viewed_at"]

    async def test_oversized_admin_email_does_not_break_listing(
        self, session, auth_user, db_conn
    ):
        oversized_admin_email = "a" * 256 + "@example.com"
        unique_last_name = f"ПакетСбой{uuid.uuid4().hex[:8]}"
        created = await _create_profile(session, auth_user, last_name=unique_last_name)

        async with session.get(
            BASE_URL,
            params={"search": unique_last_name},
            headers={"X-Admin-Email": oversized_admin_email},
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert any(item["user_id"] == created["user_id"] for item in body["items"])
        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert rows == []


class TestAuditFailureDoesNotBreakProfileRead:
    """Issue #130: сбой записи аудита (ошибка insert на стороне БД) не должен
    ломать уже успешно прочитанный профиль — см. code review #129 п.1."""

    OVERSIZED_ADMIN_EMAIL = "a" * 256 + "@example.com"

    async def test_get_profile_succeeds_when_audit_insert_fails(
        self, session, auth_user, db_conn
    ):
        created = await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}",
            headers={"X-Admin-Email": self.OVERSIZED_ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert body == created
        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert rows == []

    async def test_get_profile_full_succeeds_when_audit_insert_fails(
        self, session, auth_user, db_conn
    ):
        created = await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}/full",
            headers={"X-Admin-Email": self.OVERSIZED_ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert body["profile"] == created
        assert body["ugc_available"] is True
        rows = await _audit_rows(db_conn, auth_user["user_id"])
        assert rows == []


class TestListAuditViews:
    """GET /api/v1/profiles/audit — потребитель: раздел «Аудит просмотра
    профилей» в admin_panel (роль audit, issue #117)."""

    async def test_recorded_view_appears_in_audit_listing(
        self, session, auth_user, db_conn
    ):
        await _create_profile(session, auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200, await response.text()

        async with session.get(f"{BASE_URL}/audit") as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert body["total"] >= 1
        assert any(
            item["admin_email"] == ADMIN_EMAIL
            and item["target_user_id"] == auth_user["user_id"]
            for item in body["items"]
        )

    async def test_pagination_limits_items_but_total_reflects_all_matches(
        self, session, auth_user, new_auth_user, db_conn
    ):
        await _create_profile(session, auth_user)
        await _create_profile(session, new_auth_user)

        async with session.get(
            f"{BASE_URL}/{auth_user['user_id']}",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200
        async with session.get(
            f"{BASE_URL}/{new_auth_user['user_id']}",
            headers={"X-Admin-Email": ADMIN_EMAIL},
        ) as response:
            assert response.status == 200

        async with session.get(
            f"{BASE_URL}/audit", params={"page": 1, "page_size": 1}
        ) as response:
            assert response.status == 200, await response.text()
            body = await response.json()

        assert len(body["items"]) == 1
        assert body["total"] >= 2
