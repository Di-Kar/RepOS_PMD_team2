"""Функциональные тесты интеграции async_api с auth_service (optional-auth).

Каталог фильмов остаётся публичным API: наличие, отсутствие или невалидность
Bearer-токена не должны влиять на код ответа — это и есть изящная деградация,
которую проверяют эти тесты.
"""

import asyncio
import os
import uuid

import aiohttp
import pytest
import pytest_asyncio

from tests.async_api.settings import test_settings


def _is_docker() -> bool:
    return os.path.exists('/.dockerenv')


AUTH_API_HOST = os.getenv(
    'AUTH_API_HOST', 'auth_service' if _is_docker() else '127.0.0.1'
)
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if _is_docker() else '8001'))
AUTH_BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1"


async def _post_json_with_retry(
    session: aiohttp.ClientSession, url: str, json_body: dict
) -> tuple:
    """POST с уважением к 429 Retry-After (RATE_LIMIT_STRICT на auth_service)."""
    while True:
        async with session.post(url, json=json_body) as response:
            status = response.status
            if status == 429:
                retry_after = float(response.headers.get('Retry-After', 2))
                await response.read()
            else:
                body = await response.json()
                return status, body
        await asyncio.sleep(retry_after + 0.2)


@pytest_asyncio.fixture(name='auth_headers')
async def auth_headers() -> dict:
    """Регистрирует и логинит одноразового пользователя в auth_service,
    возвращает готовый заголовок Authorization с настоящим access-токеном."""
    email = f"async_api_it_{uuid.uuid4().hex[:12]}@example.com"
    password = "IntegrationPass123!"
    async with aiohttp.ClientSession() as session:
        status, body = await _post_json_with_retry(
            session,
            f"{AUTH_BASE_URL}/auth/register",
            {"email": email, "password": password, "full_name": "Async Api IT"},
        )
        assert status == 201, body

        status, tokens = await _post_json_with_retry(
            session,
            f"{AUTH_BASE_URL}/auth/login",
            {"email": email, "password": password},
        )
        assert status == 200, tokens

    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.asyncio
async def test_genres_list_without_token(
    es_write_data, es_data_genres, make_get_request
):
    """Без заголовка Authorization каталог доступен как обычно."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    response = await make_get_request('/genres', '')

    assert response['status'] == 200
    assert isinstance(response['body'], list)


@pytest.mark.asyncio
async def test_genres_list_with_valid_token(
    es_write_data, es_data_genres, auth_headers, aiohttp_session
):
    """С валидным токеном auth_service подтверждает пользователя, но список тот же."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)
    base_url = test_settings.fastapi_settings.get_host()

    async with aiohttp_session.get(
        f"{base_url}/api/v1/genres", headers=auth_headers
    ) as response:
        assert response.status == 200
        body = await response.json()
        assert isinstance(body, list)


@pytest.mark.asyncio
async def test_genres_list_with_invalid_token(
    es_write_data, es_data_genres, aiohttp_session
):
    """Невалидный/просроченный токен не должен блокировать публичный каталог —
    auth_service отвечает 401, async_api трактует это как анонимный доступ."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)
    base_url = test_settings.fastapi_settings.get_host()

    async with aiohttp_session.get(
        f"{base_url}/api/v1/genres",
        headers={"Authorization": "Bearer not-a-real-token"},
    ) as response:
        assert response.status == 200
        body = await response.json()
        assert isinstance(body, list)
