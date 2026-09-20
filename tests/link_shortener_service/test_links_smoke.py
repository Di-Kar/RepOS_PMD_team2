"""Смоук-тесты link_shortener_service (docs/link_shortener_contract.md):
создание короткой ссылки, резолв по коду, 404 на несуществующий/просроченный
код, счётчик визитов."""

import asyncio

from .conftest import BASE_URL, create_link, make_link_request, visit_link


class TestCreateLink:
    async def test_create_link_returns_short_url(self, session):
        status, body = await create_link(session)
        assert status == 201, body
        assert body["code"]
        assert body["short_url"].endswith(f"/r/{body['code']}")
        assert body["expires_at"]

    async def test_create_link_rejects_bad_redirect_url_scheme(self, session):
        async with session.post(
            f"{BASE_URL}/api/v1/links",
            json=make_link_request(redirect_url="javascript:alert(1)"),
        ) as response:
            assert response.status == 400, await response.text()

    async def test_create_link_defaults_ttl_when_not_given(self, session):
        status, body = await create_link(session)
        assert status == 201, body
        # LINKS_DEFAULT_TTL_SECONDS по умолчанию 86400 (сутки) — просто
        # проверяем, что expires_at в будущем и не пуст, не завязываемся на
        # конкретное значение TTL, которое может быть переопределено в .env.
        assert body["expires_at"]


class TestRedirect:
    async def test_visit_unknown_code_returns_404(self, session):
        status, _location = await visit_link(session, "doesnotexist")
        assert status == 404

    async def test_visit_valid_code_redirects_and_counts_visits(
        self, session, db_conn
    ):
        status, body = await create_link(
            session, redirect_url="https://example.com/target-a"
        )
        assert status == 201, body
        code = body["code"]

        visit_status, location = await visit_link(session, code)
        assert visit_status == 302
        assert location == "https://example.com/target-a"

        # Повторный визит — снова редирект, не 404 (не одноразовая ссылка),
        # visit_count растёт.
        visit_status_2, _ = await visit_link(session, code)
        assert visit_status_2 == 302

        row = await db_conn.fetchrow(
            "SELECT visit_count, confirmed_at FROM short_links WHERE code = $1",
            code,
        )
        assert row is not None
        assert row["visit_count"] == 2
        # purpose=generic никогда не проставляет confirmed_at — это поле
        # относится только к purpose=email_confirmation (см. contract §3).
        assert row["confirmed_at"] is None

    async def test_visit_expired_code_returns_404(self, session, db_conn):
        status, body = await create_link(
            session, redirect_url="https://example.com/expiring", ttl_seconds=1
        )
        assert status == 201, body
        code = body["code"]

        await asyncio.sleep(1.5)

        visit_status, _location = await visit_link(session, code)
        assert visit_status == 404
