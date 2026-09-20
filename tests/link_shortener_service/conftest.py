"""Фикстуры HTTP-смоук-тестов link_shortener_service (black-box) — по образцу
tests/notification_api/conftest.py."""

import os
import uuid

import aiohttp
import asyncpg
import pytest_asyncio


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


LINK_SHORTENER_API_HOST = os.getenv(
    'LINK_SHORTENER_API_HOST', 'link_shortener_service' if is_docker() else '127.0.0.1'
)
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8006.
LINK_SHORTENER_API_PORT = int(
    os.getenv('LINK_SHORTENER_API_PORT', '8000' if is_docker() else '8006')
)
BASE_URL = f"http://{LINK_SHORTENER_API_HOST}:{LINK_SHORTENER_API_PORT}"

API_KEY = os.getenv('LINKS_API_KEY', '')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

LINKS_POSTGRES_HOST = os.getenv('LINKS_POSTGRES_HOST', 'link_shortener_postgres')
LINKS_POSTGRES_PORT = int(os.getenv('LINKS_POSTGRES_PORT', '5432'))
LINKS_POSTGRES_USER = os.getenv('LINKS_POSTGRES_USER', 'links_user')
LINKS_POSTGRES_PASSWORD = os.getenv('LINKS_POSTGRES_PASSWORD', 'links_secret')
LINKS_POSTGRES_DB = os.getenv('LINKS_POSTGRES_DB', 'links_db')


def make_link_request(**overrides) -> dict:
    request = {
        "source_service": "smoke-test",
        "purpose": "generic",
        "redirect_url": "https://example.com/target",
    }
    request.update(overrides)
    return request


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


async def create_link(session: aiohttp.ClientSession, **overrides) -> tuple:
    async with session.post(
        f"{BASE_URL}/api/v1/links",
        json=make_link_request(**overrides),
        headers=HEADERS,
    ) as response:
        return response.status, await response.json()


async def visit_link(session: aiohttp.ClientSession, code: str) -> tuple:
    """GET /r/{code} без авто-редиректа — возвращает (status, location);
    статус и заголовок Location интересны сами по себе, а не страница,
    куда ведёт редирект."""
    async with session.get(
        f"{BASE_URL}/r/{code}", allow_redirects=False
    ) as response:
        return response.status, response.headers.get("Location")


@pytest_asyncio.fixture(name='db_conn')
async def db_conn():
    conn = await asyncpg.connect(
        host=LINKS_POSTGRES_HOST,
        port=LINKS_POSTGRES_PORT,
        user=LINKS_POSTGRES_USER,
        password=LINKS_POSTGRES_PASSWORD,
        database=LINKS_POSTGRES_DB,
    )
    yield conn
    await conn.close()


def random_uuid() -> str:
    return str(uuid.uuid4())
