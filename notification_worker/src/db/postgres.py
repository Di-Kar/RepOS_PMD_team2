"""Пул подключений asyncpg к notifications_db — общей физической БД
notification_api (notification_log) и notification_admin_panel
(message_templates/notifications/notification_contents/notification_history).

Воркер не Django-процесс и не должен подключать Django ORM ради нескольких
таблиц — пишет прямым SQL (см. src/db/queries.py). Используется asyncpg
напрямую (не SQLAlchemy, как у notification_api) — нет необходимости в
ORM-моделях для операций, которые в основном сводятся к нескольким точечным
INSERT/UPDATE в рамках одной транзакции на сообщение."""

import logging
from typing import Optional

import asyncpg

from src.core.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
    )
    logger.info(f"Postgres pool started: {settings.postgres_host}:{settings.postgres_port}")


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed.")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Postgres pool is not initialized")
    return _pool
