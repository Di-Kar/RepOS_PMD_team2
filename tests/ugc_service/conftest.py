"""Конфигурация и фикстуры для тестов ugc_service."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import redis.asyncio as redis

import pytest

# --------------------------------------------------------------------------- #
#  Находим директорию ugc_service/src/ по нескольким кандидатам:
#    1. /ugc_service/src/          — docker-путь (при смонтированном volume)
#    2. Относительный путь от conftest.py — локальный запуск (./ugc_service)
# --------------------------------------------------------------------------- #

_SRC_ROOT = None

# 1. Docker-путь
_docker_path = Path('/ugc_service')
_docker_src = _docker_path / 'src'
if _docker_src.is_dir() and (_docker_src / '__init__.py').exists():
    _SRC_ROOT = _docker_src

# 2. Относительный путь от conftest.py (локальный запуск)
if _SRC_ROOT is None:
    _rel_path = Path(__file__).parent.parent / 'ugc_service' / 'src'
    if _rel_path.is_dir() and (_rel_path / '__init__.py').exists():
        _SRC_ROOT = _rel_path

# 3. От текущего working directory (pytest запускается из tests/)
if _SRC_ROOT is None:
    _cwd_path = Path.cwd().parent / 'ugc_service' / 'src'
    if _cwd_path.is_dir() and (_cwd_path / '__init__.py').exists():
        _SRC_ROOT = _cwd_path

if _SRC_ROOT is not None:
    if str(_SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(_SRC_ROOT))


@pytest.fixture
def mock_beanie():
    """Мокаем Beanie для тестов без реальной MongoDB."""
    mock_doc = MagicMock()
    mock_doc.insert = AsyncMock()
    mock_doc.delete = AsyncMock()
    mock_doc.save = AsyncMock()
    mock_doc.find_one = AsyncMock(return_value=None)
    mock_doc.find = MagicMock()
    mock_doc.find.return_value.skip = MagicMock()
    mock_doc.find.return_value.limit = MagicMock()
    mock_doc.find.return_value.sort = MagicMock()
    mock_doc.find.return_value.to_list = AsyncMock(return_value=[])
    mock_doc.get = AsyncMock(return_value=None)
    return mock_doc

@pytest.fixture(autouse=True)
async def clear_rate_limits_before_each_test():
    """
    Очищает базу данных Redis #1 (где хранятся счётчики rate limiter)
    перед каждым тестом, чтобы избежать загрязнения состояния между тестами.
    """
    try:
        # Подключаемся к тому же Redis, что и ugc_service
        r = redis.Redis(host="ugc_redis", port=6379, db=1, decode_responses=True)
        await r.flushdb()
        yield
        await r.close()
    except Exception as e:
        # Если Redis недоступен (например, в изолированном unit-тесте без docker network),
        # просто пропускаем очистку, чтобы не ронять тесты
        print(f"\n[WARNING] Не удалось очистить Redis для rate limiter: {e}")
        yield