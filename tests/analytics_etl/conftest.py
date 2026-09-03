"""Общие фикстуры для тестов analytics_etl."""

import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Находим директорию analytics_etl/src/ по нескольким кандидатам:
#    1. /analytics_etl/src/        — docker-путь (при смонтированном volume)
#    2. Относительный путь от conftest.py — локальный запуск (./analytics_etl)
# --------------------------------------------------------------------------- #

_SRC_ROOT = None

# 1. Docker-путь
_docker_path = Path('/analytics_etl')
_docker_src = _docker_path / 'src'
if _docker_src.is_dir() and (_docker_src / '__init__.py').exists():
    _SRC_ROOT = _docker_src

# 2. Относительный путь от conftest.py (локальный запуск)
if _SRC_ROOT is None:
    _rel_path = Path(__file__).parent.parent / 'analytics_etl' / 'src'
    if _rel_path.is_dir() and (_rel_path / '__init__.py').exists():
        _SRC_ROOT = _rel_path

# 3. От текущего working directory (pytest запускается из tests/)
if _SRC_ROOT is None:
    _cwd_path = Path.cwd().parent / 'analytics_etl' / 'src'
    if _cwd_path.is_dir() and (_cwd_path / '__init__.py').exists():
        _SRC_ROOT = _cwd_path

if _SRC_ROOT is not None:
    if str(_SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(_SRC_ROOT))
