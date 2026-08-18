"""Общий conftest для всех тестов проекта: делает пакет shared/event_schemas
импортируемым независимо от того, где запущены тесты.

Кандидаты пути:
  1. /shared              — docker-путь (смонтированный volume, см. docker-compose.yml)
  2. ../shared от этого файла — локальный запуск (репозиторий на диске)
"""

import sys
from pathlib import Path

_SHARED_ROOT = None

_docker_path = Path('/shared')
if _docker_path.is_dir() and (_docker_path / 'event_schemas.py').exists():
    _SHARED_ROOT = _docker_path

if _SHARED_ROOT is None:
    _rel_path = Path(__file__).parent.parent / 'shared'
    if _rel_path.is_dir() and (_rel_path / 'event_schemas.py').exists():
        _SHARED_ROOT = _rel_path

if _SHARED_ROOT is not None and str(_SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHARED_ROOT))
