# src/core/redis_client.py
"""Асинхронный Redis-клиент для кэша статистики фильмов."""

import logging
from redis.asyncio import Redis


from config import settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Ленивая инициализация синглтона Redis-клиента."""
    global _redis
    if _redis is None:
        _redis = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db_cache,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            retry_on_timeout=True,
        )
    return _redis


async def close_redis() -> None:
    """Закрыть соединение при shutdown приложения."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
