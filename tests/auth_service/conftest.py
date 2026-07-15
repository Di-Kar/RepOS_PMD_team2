"""Фикстуры HTTP-смоук-тестов auth_service (black-box, только HTTP)."""
import os
import uuid

import aiohttp
import pytest_asyncio


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


AUTH_API_HOST = os.getenv('AUTH_API_HOST', 'auth_service' if is_docker() else '127.0.0.1')
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8001.
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if is_docker() else '8001'))
BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1"

PASSWORD = "SmokePass123!"


def bearer(tokens: dict) -> dict:
    """Заголовок Authorization из пары токенов."""
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture(name='session')
async def session():
    """HTTP-сессия."""
    async with aiohttp.ClientSession() as http_session:
        yield http_session


@pytest_asyncio.fixture(name='new_user')
async def new_user(session):
    """Регистрирует пользователя со случайным email, возвращает его данные."""
    email = f"smoke_{uuid.uuid4().hex[:12]}@example.com"
    async with session.post(
        f"{BASE_URL}/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Smoke Tester"},
    ) as response:
        assert response.status == 201, await response.text()
        body = await response.json()
    return {"id": body["id"], "email": email, "password": PASSWORD}


@pytest_asyncio.fixture(name='login')
async def login(session):
    """Фабрика: логинится и возвращает пару токенов."""

    async def _login(user: dict, password: str | None = None) -> dict:
        async with session.post(
            f"{BASE_URL}/auth/login",
            json={"email": user["email"], "password": password or user["password"]},
        ) as response:
            assert response.status == 200, await response.text()
            return await response.json()

    return _login


@pytest_asyncio.fixture(name='tokens')
async def tokens(new_user, login):
    """Пара токенов свежезарегистрированного пользователя."""
    return await login(new_user)
