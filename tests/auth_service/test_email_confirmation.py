"""Подтверждение email по короткой ссылке из welcome-письма.

- POST /api/v1/auth/internal/users/{id}/confirm-email (см.
  auth_service/src/api/v1/internal.py) — идемпотентный internal-эндпоинт,
  вызываемый link_shortener_service.
- Полный сценарий "регистрация -> welcome-письмо содержит короткую ссылку ->
  переход по ссылке подтверждает email" — end-to-end, требует поднятого
  link_shortener_service (см. docs/link_shortener_contract.md)."""

import os
import uuid

import aiohttp

from .conftest import BASE_URL, PASSWORD, post_json

INTERNAL_API_KEY = os.getenv('AUTH_INTERNAL_API_KEY', '')
INTERNAL_HEADERS = (
    {"X-Internal-Api-Key": INTERNAL_API_KEY} if INTERNAL_API_KEY else {}
)


async def confirm_email(session: aiohttp.ClientSession, user_id: str) -> tuple:
    async with session.post(
        f"{BASE_URL}/auth/internal/users/{user_id}/confirm-email",
        headers=INTERNAL_HEADERS,
    ) as response:
        try:
            body = await response.json()
        except aiohttp.ContentTypeError:
            body = None
        return response.status, body


class TestConfirmEmailInternalEndpoint:
    async def test_confirm_email_for_unknown_user_returns_404(self, session):
        status, body = await confirm_email(session, str(uuid.uuid4()))
        assert status == 404, body

    async def test_confirm_email_is_idempotent(self, session):
        email = f"confirm_email_{uuid.uuid4().hex[:12]}@example.com"
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {"email": email, "password": PASSWORD, "full_name": "Confirm Me"},
        )
        assert status == 201, body
        user_id = body["id"]

        first_status, _ = await confirm_email(session, user_id)
        assert first_status == 204

        # Повторный вызов для уже подтверждённого пользователя — снова 204,
        # не ошибка (несколько кликов по ещё не истёкшей ссылке).
        second_status, _ = await confirm_email(session, user_id)
        assert second_status == 204

    async def test_confirm_email_requires_valid_internal_api_key(self, session):
        if not INTERNAL_API_KEY:
            # Проверка X-Internal-Api-Key отключена в этом окружении (dev) —
            # AUTH_INTERNAL_API_KEY пуст, см. src/api/v1/dependencies.py.
            return
        async with session.post(
            f"{BASE_URL}/auth/internal/users/{uuid.uuid4()}/confirm-email",
            headers={"X-Internal-Api-Key": "wrong-key"},
        ) as response:
            assert response.status == 401
