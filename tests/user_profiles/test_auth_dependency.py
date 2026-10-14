"""Юнит-тесты get_current_user_id (user_profiles) — без БД/сети: HTTP-клиент
подменён. Проверяют, что токен проверяется через auth_service/token/verify
(без обратного вызова в user_profiles) и что недоступность auth_service (503)
отличается от неверного токена (401).

dependencies.py грузится через importlib с заглушкой src.core.config — по той
же причине, что и в test_schemas.py (имя "src" занято пакетами других сервисов)."""

import importlib.util
import sys
import types
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

_docker_path = Path('/user_profiles/src/api/v1/dependencies.py')
_DEPS_PATH = (
    _docker_path
    if _docker_path.is_file()
    else Path(__file__).parent.parent.parent
    / 'user_profiles' / 'src' / 'api' / 'v1' / 'dependencies.py'
)

AUTH_URL = "http://auth.test/api/v1/auth"


@pytest.fixture(name='deps')
def deps_fixture(monkeypatch):
    settings = types.SimpleNamespace(
        auth_service_url=AUTH_URL, auth_service_timeout=3.0, internal_api_key=""
    )
    for name in ('src', 'src.core'):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    config = types.ModuleType('src.core.config')
    config.settings = settings
    monkeypatch.setitem(sys.modules, 'src.core.config', config)

    spec = importlib.util.spec_from_file_location(
        'profiles_deps_under_test', _DEPS_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_request(token: str | None = "tok") -> Request:
    headers = [(b'authorization', f'Bearer {token}'.encode())] if token else []
    return Request({'type': 'http', 'headers': headers})


def patch_transport(monkeypatch, deps, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        deps,
        'AsyncClient',
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def test_valid_token_uses_token_verify_endpoint(deps, monkeypatch):
    user_id = uuid.uuid4()
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": str(user_id)})

    patch_transport(monkeypatch, deps, handler)
    assert await deps.get_current_user_id(make_request()) == user_id
    assert seen == ["/api/v1/auth/token/verify"]


async def test_invalid_token_returns_401(deps, monkeypatch):
    patch_transport(monkeypatch, deps, lambda r: httpx.Response(401, json={}))
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_id(make_request())
    assert exc.value.status_code == 401


async def test_missing_header_returns_401(deps):
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_id(make_request(token=None))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_auth_5xx_returns_503(deps, monkeypatch, status_code):
    patch_transport(monkeypatch, deps, lambda r: httpx.Response(status_code))
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_id(make_request())
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "auth_unavailable"


async def test_auth_timeout_returns_503(deps, monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    patch_transport(monkeypatch, deps, handler)
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_id(make_request())
    assert exc.value.status_code == 503


async def test_rate_limit_is_passed_through(deps, monkeypatch):
    patch_transport(
        monkeypatch,
        deps,
        lambda r: httpx.Response(429, headers={"Retry-After": "7"}),
    )
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user_id(make_request())
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "7"
