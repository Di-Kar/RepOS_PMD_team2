"""Общие фикстуры для тестов analytics_etl."""

import sys
import os
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Находим директорию analytics_etl по нескольким кандидатам:
#    1. /analytics_etl          — docker-путь (при смонтированном volume)
#    2. Относительный путь от conftest.py — локальный запуск (./analytics_etl)
# --------------------------------------------------------------------------- #

_ETL_ROOT = None

# 1. Docker-путь
_docker_path = Path('/analytics_etl')
if _docker_path.is_dir() and (_docker_path / '__init__.py').exists():
    _ETL_ROOT = _docker_path

# 2. Относительный путь от conftest.py (локальный запуск)
if _ETL_ROOT is None:
    _rel_path = Path(__file__).parent.parent / 'analytics_etl'
    if _rel_path.is_dir() and (_rel_path / '__init__.py').exists():
        _ETL_ROOT = _rel_path

# 3. От текущего working directory (pytest запускается из tests/)
if _ETL_ROOT is None:
    _cwd_path = Path.cwd().parent / 'analytics_etl'
    if _cwd_path.is_dir() and (_cwd_path / '__init__.py').exists():
        _ETL_ROOT = _cwd_path

if _ETL_ROOT is not None:
    if str(_ETL_ROOT) not in sys.path:
        sys.path.insert(0, str(_ETL_ROOT))
    # Также добавляем корень проекта (для config.py и других общих модулей)
    _project_root = _ETL_ROOT.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))
