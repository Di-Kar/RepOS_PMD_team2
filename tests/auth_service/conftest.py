"""Фикстуры HTTP-смоук-тестов auth_service (black-box, только HTTP)."""

import asyncio
import os
import uuid

import aiohttp
import pytest_asyncio


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


AUTH_API_HOST = os.getenv(
    'AUTH_API_HOST', 'auth_service' if is_docker() else '127.0.0.1'
)
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8001.
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if is_docker() else '8001'))
BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1"

PASSWORD = "SmokePass123!"

# Фиксированный email переиспользуется между прогонами — см. shared_user.
SHARED_USER_EMAIL = "shared_smoke_user@example.com"
SHARED_USER_PASSWORD = "SharedSmokePass123!"


def bearer(tokens: dict) -> dict:
    """Заголовок Authorization из пары токенов."""
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def post_json(
    session: aiohttp.ClientSession,
    url: str,
    json_body: dict,
    headers: dict | None = None,
) -> tuple:
    """POST с уважением к 429 Retry-After (register/login/change-password
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


@pytest_asyncio.fixture(name='session')
async def session():
    """HTTP-сессия."""
    async with aiohttp.ClientSession() as http_session:
        yield http_session


@pytest_asyncio.fixture(name='new_user')
async def new_user(session):
    """Регистрирует пользователя со случайным email, возвращает его данные."""
    email = f"smoke_{uuid.uuid4().hex[:12]}@example.com"
    status, body = await post_json(
        session,
        f"{BASE_URL}/auth/register",
        {"email": email, "password": PASSWORD, "full_name": "Smoke Tester"},
    )
    assert status == 201, body
    return {"id": body["id"], "email": email, "password": PASSWORD}


@pytest_asyncio.fixture(name='login')
async def login(session):
    """Фабрика: логинится и возвращает пару токенов."""

    async def _login(user: dict, password: str | None = None) -> dict:
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/login",
            {"email": user["email"], "password": password or user["password"]},
        )
        assert status == 200, body
        return body

    return _login


@pytest_asyncio.fixture(name='shared_user', scope='session', loop_scope='session')
async def shared_user():
    """Один пользователь на весь прогон — экономит /register под лимитом.
    Не годится тестам, которые убивают/ротируют сессии или меняют пароль
    (те берут свой new_user)."""
    async with aiohttp.ClientSession() as http_session:
        status, body = await post_json(
            http_session,
            f"{BASE_URL}/auth/register",
            {
                "email": SHARED_USER_EMAIL,
                "password": SHARED_USER_PASSWORD,
                "full_name": "Shared Smoke User",
            },
        )
        if status == 201:
            return {
                "id": body["id"],
                "email": SHARED_USER_EMAIL,
                "password": SHARED_USER_PASSWORD,
            }
        assert status == 409, body  # уже зарегистрирован в прошлом прогоне

        status, login_body = await post_json(
            http_session,
            f"{BASE_URL}/auth/login",
            {"email": SHARED_USER_EMAIL, "password": SHARED_USER_PASSWORD},
        )
        assert status == 200, login_body

        async with http_session.get(
            f"{BASE_URL}/auth/profile",
            headers={"Authorization": f"Bearer {login_body['access_token']}"},
        ) as response:
            assert response.status == 200, await response.text()
            profile = await response.json()

    return {
        "id": profile["id"],
        "email": SHARED_USER_EMAIL,
        "password": SHARED_USER_PASSWORD,
    }


@pytest_asyncio.fixture(name='shared_tokens', scope='session', loop_scope='session')
async def shared_tokens(shared_user):
    """Один залогиненный сеанс shared_user на весь прогон — для тестов,
    которым достаточно валидного токена и которые не убивают и не ротируют
    именно эту сессию (иначе сломают все остальные тесты на этой фикстуре)."""
    async with aiohttp.ClientSession() as http_session:
        status, body = await post_json(
            http_session,
            f"{BASE_URL}/auth/login",
            {"email": shared_user["email"], "password": shared_user["password"]},
        )
        assert status == 200, body
    return body


@pytest_asyncio.fixture(name='tokens')
async def tokens(shared_user, login):
    """Собственная (не расшаренная) сессия — для тестов, которые ротируют
    или убивают именно эту сессию (refresh/logout). Учётка при этом общая
    (shared_user), чтобы не плодить лишние /register."""
    return await login(shared_user)
