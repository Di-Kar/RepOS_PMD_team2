"""Юнит-тесты src/services/ugc_client.py (user_profiles) — без сети: HTTP
подменён. Любой некорректный ответ ugc_service (в том числе 200 с телом, не
соответствующим схеме) должен давать None — вызывающий код отдаёт профиль с
ugc_available=False, а не 500.

Модули грузятся через importlib с заглушкой src.core.config — по той же
причине, что и в test_schemas.py (имя "src" занято пакетами других сервисов)."""

import importlib.util
import sys
import types
import uuid
from pathlib import Path

import httpx
import pytest

_docker_root = Path('/user_profiles')
_ROOT = (
    _docker_root
    if _docker_root.is_dir()
    else Path(__file__).parent.parent.parent / 'user_profiles'
)


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name='client')
def client_fixture(monkeypatch):
    for name in ('src', 'src.core', 'src.models'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    config = types.ModuleType('src.core.config')
    config.settings = types.SimpleNamespace(
        ugc_service_url='http://ugc.test',
        ugc_service_timeout=3.0,
        ugc_internal_api_key='k',
    )
    monkeypatch.setitem(sys.modules, 'src.core.config', config)
    monkeypatch.setitem(
        sys.modules,
        'src.models.schemas',
        _load('src.models.schemas', 'src/models/schemas.py'),
    )
    module = _load('ugc_client_under_test', 'src/services/ugc_client.py')
    yield module
    sys.modules.pop('src.models.schemas', None)


def patch_transport(monkeypatch, module, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        module,
        'AsyncClient',
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


FILM = str(uuid.uuid4())
VALID = {
    "bookmarks": [{"film_id": FILM, "added_at": "2026-01-01T00:00:00Z"}],
    "ratings": [{"film_id": FILM, "rating": 8, "updated_at": "2026-01-01T00:00:00Z"}],
    "reviews": [
        {
            "id": "r1",
            "film_id": FILM,
            "title": "t",
            "rating": 7,
            "published_at": "2026-01-01T00:00:00Z",
            "likes_count": 1,
            "dislikes_count": 0,
        }
    ],
}


async def call(client, monkeypatch, response: httpx.Response):
    patch_transport(monkeypatch, client, lambda request: response)
    return await client.get_user_ugc_summary(uuid.uuid4())


async def test_valid_response_returns_typed_summary(client, monkeypatch):
    summary = await call(client, monkeypatch, httpx.Response(200, json=VALID))
    assert summary is not None
    assert str(summary.bookmarks[0].film_id) == FILM
    assert summary.ratings[0].rating == 8
    assert summary.reviews[0].id == "r1"


async def test_missing_keys_default_to_empty_lists(client, monkeypatch):
    summary = await call(client, monkeypatch, httpx.Response(200, json={}))
    assert summary is not None
    assert summary.bookmarks == summary.ratings == summary.reviews == []


@pytest.mark.parametrize(
    "body",
    [
        {"bookmarks": None},
        {"ratings": [{}]},
        {"reviews": [{"id": "r1"}]},
        {"bookmarks": [{"film_id": "not-a-uuid", "added_at": "x"}]},
        {"bookmarks": "oops"},
        None,
        [],
        True,
    ],
)
async def test_invalid_body_returns_none(client, monkeypatch, body):
    assert await call(client, monkeypatch, httpx.Response(200, json=body)) is None


async def test_non_json_body_returns_none(client, monkeypatch):
    response = httpx.Response(200, content=b"<html>bad gateway</html>")
    assert await call(client, monkeypatch, response) is None


async def test_non_200_returns_none(client, monkeypatch):
    assert await call(client, monkeypatch, httpx.Response(503)) is None


async def test_network_error_returns_none(client, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    patch_transport(monkeypatch, client, handler)
    assert await client.get_user_ugc_summary(uuid.uuid4()) is None
