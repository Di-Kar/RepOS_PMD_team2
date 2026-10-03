"""Фикстуры HTTP-смоук-тестов user_profiles (black-box, только HTTP +
asyncpg) — по образцу tests/auth_service/conftest.py (регистрация/логин,
ожидание 429) и tests/link_shortener_service/conftest.py (BASE_URL,
db_conn)."""

import asyncio
import os
import uuid

import aiohttp
import asyncpg
import pytest_asyncio


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


USER_PROFILES_API_HOST = os.getenv(
    'USER_PROFILES_API_HOST', 'user_profiles' if is_docker() else '127.0.0.1'
)
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8007.
USER_PROFILES_API_PORT = int(
    os.getenv('USER_PROFILES_API_PORT', '8000' if is_docker() else '8007')
)
BASE_URL = f"http://{USER_PROFILES_API_HOST}:{USER_PROFILES_API_PORT}/api/v1/profiles"

AUTH_API_HOST = os.getenv(
    'AUTH_API_HOST', 'auth_service' if is_docker() else '127.0.0.1'
)
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if is_docker() else '8001'))
AUTH_BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1/auth"

PROFILES_POSTGRES_HOST = os.getenv('PROFILES_POSTGRES_HOST', 'user_profiles_postgres')
PROFILES_POSTGRES_PORT = int(os.getenv('PROFILES_POSTGRES_PORT', '5432'))
PROFILES_POSTGRES_USER = os.getenv('PROFILES_POSTGRES_USER', 'profiles_user')
PROFILES_POSTGRES_PASSWORD = os.getenv('PROFILES_POSTGRES_PASSWORD', 'profiles_secret')
PROFILES_POSTGRES_DB = os.getenv('PROFILES_POSTGRES_DB', 'profiles_db')

PASSWORD = "SmokePass123!"


async def post_json(
    session: aiohttp.ClientSession,
    url: str,
    json_body: dict,
    headers: dict | None = None,
) -> tuple:
    """POST с уважением к 429 Retry-After (auth_service/register и /login
    ограничены RATE_LIMIT_STRICT)."""
    while True:
        async with session.post(url, json=json_body, headers=headers) as response:
            status = response.status
            if status == 429:
                retry_after = float(response.headers.get('Retry-After', 2))
                await response.read()
            else:
                try:
                    body = await response.json()
                except aiohttp.ContentTypeError:
                    body = {}
                return status, body
        await asyncio.sleep(retry_after + 0.2)


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


async def register_and_login(session: aiohttp.ClientSession) -> dict:
    """Регистрирует нового пользователя auth_service и логинит его."""
    email = f"profiles_smoke_{uuid.uuid4().hex[:12]}@example.com"
    status, body = await post_json(
        session,
        f"{AUTH_BASE_URL}/register",
        {"email": email, "password": PASSWORD, "full_name": "Profiles Smoke Tester"},
    )
    assert status == 201, body
    status, tokens = await post_json(
        session, f"{AUTH_BASE_URL}/login", {"email": email, "password": PASSWORD}
    )
    assert status == 200, tokens
    return {"user_id": body["id"], "tokens": tokens}


@pytest_asyncio.fixture(name='auth_user')
async def auth_user(session):
    """Свежий, изолированный пользователь auth_service на каждый тест: в
    отличие от shared_user в tests/auth_service, профиль создаётся/удаляется
    по одному на user_id, и тесты не должны мешать друг другу."""
    return await register_and_login(session)


@pytest_asyncio.fixture(name='new_auth_user')
async def new_auth_user(session):
    """Второй независимый пользователь — для тестов конфликта телефона между
    двумя разными user_id."""
    return await register_and_login(session)


@pytest_asyncio.fixture(name='db_conn')
async def db_conn():
    conn = await asyncpg.connect(
        host=PROFILES_POSTGRES_HOST,
        port=PROFILES_POSTGRES_PORT,
        user=PROFILES_POSTGRES_USER,
        password=PROFILES_POSTGRES_PASSWORD,
        database=PROFILES_POSTGRES_DB,
    )
    yield conn
    await conn.close()


def make_profile_request(**overrides) -> dict:
    request = {
        "first_name": "Иван",
        "last_name": "Иванов",
        "phone": f"+7999{uuid.uuid4().int % 10_000_000:07d}",
    }
    request.update(overrides)
    return request
