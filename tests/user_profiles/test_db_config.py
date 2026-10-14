"""Юнит-тесты сборки строки подключения к БД (user_profiles/src/core/config.py)
— без БД. Пароль со спецсимволами (@, :, /, #, %) не должен ломать разбор
URL ни в приложении, ни в Alembic.

config.py грузится через importlib по прямому пути — по той же причине, что
и в test_schemas.py (имя "src" занято пакетами других сервисов)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_docker_path = Path('/user_profiles/src/core/config.py')
_CONFIG_PATH = (
    _docker_path
    if _docker_path.is_file()
    else Path(__file__).parent.parent.parent
    / 'user_profiles' / 'src' / 'core' / 'config.py'
)

_spec = importlib.util.spec_from_file_location(
    'user_profiles_config_under_test', _CONFIG_PATH
)
_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config)

PASSWORDS = [
    "plain",
    "p@ss",
    "a@evil-host:1234/db",
    "us:er/pa#ss?x=1",
    "100%done",
    "%40already%2Fencoded",
    "пароль",
]


def make_settings(password: str):
    return _config.Settings(
        PROFILES_POSTGRES_HOST="db.internal",
        PROFILES_POSTGRES_PORT=5433,
        PROFILES_POSTGRES_DB="profiles",
        PROFILES_POSTGRES_USER="app_user",
        PROFILES_POSTGRES_PASSWORD=password,
    )


@pytest.mark.parametrize("password", PASSWORDS)
def test_url_keeps_password_and_host_separate(password):
    url = make_settings(password).postgres_url
    assert url.password == password
    assert url.username == "app_user"
    assert url.host == "db.internal"
    assert url.port == 5433
    assert url.database == "profiles"
    assert url.drivername == "postgresql+asyncpg"


@pytest.mark.parametrize("password", PASSWORDS)
def test_engine_receives_password_unchanged(password):
    """Движок (его же использует alembic/env.py) получает URL объектом, пароль
    не искажается — в отличие от строкового DSN, где SQLAlchemy 2.0 не
    кодирует % и пароль "%40x" превращается в "@x"."""
    engine = create_async_engine(make_settings(password).postgres_url)
    assert engine.url.password == password
    assert engine.url.host == "db.internal"


def test_string_dsn_is_not_safe_for_percent_passwords():
    """Страховка: фиксирует причину, по которой URL нельзя превращать в
    строку. Если этот тест начнёт падать, SQLAlchemy починил кодирование %."""
    url = make_settings("%40x").postgres_url
    assert make_url(url.render_as_string(hide_password=False)).password != "%40x"
