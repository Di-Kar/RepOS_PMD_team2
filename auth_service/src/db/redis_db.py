"""
Модуль подключения к базе данных Redis.
Предоставляет асинхронный клиент Redis и утилиты для управления токенами/кэшем.
"""
import logging
from typing import AsyncGenerator, Optional

from redis.asyncio import ConnectionPool, Redis

from src.core.config import settings

logger = logging.getLogger(__name__)

# Глобальный пул соединений
redis_pool: Optional[ConnectionPool] = None

# Глобальный экземпляр клиента Redis
redis_client: Optional[Redis] = None

async def get_redis_pool() -> ConnectionPool:
    """
    Получает или создает глобальный пул соединений Redis.
    Returns:
        ConnectionPool: Экземпляр пула соединений Redis.
    """
    global redis_pool
    if redis_pool is None:
        redis_pool = ConnectionPool.from_url(
            settings.redis_dsn,
            decode_responses=True,
            max_connections=50,
            retry_on_timeout=True,
        )
        logger.info("Redis connection pool initialized.")
    return redis_pool
 
async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Зависимость FastAPI, предоставляющая клиент Redis для обработки одного HTTP-запроса.
    """
    pool = await get_redis_pool()
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()
 
async def init_redis() -> None:
    """
    Инициализирует подключение к Redis и проверяет его доступность.
    Должен вызываться при запуске приложения (через механизм lifespan).
    """
    global redis_client
    try:
        pool = await get_redis_pool()
        redis_client = Redis(connection_pool=pool)
        await redis_client.ping()
        logger.info("Redis connection established and verified successfully.")
    except Exception as e:
        logger.error(f"Failed to connect to Redis on startup: {e}")
        raise
 
async def close_redis() -> None:
    """
    Корректно закрывает соединения с Redis.
    """
    global redis_client, redis_pool
    if redis_client:
        await redis_client.aclose()
        redis_client = None
        logger.info("Global Redis client closed.")
    if redis_pool:
        await redis_pool.disconnect()
        redis_pool = None
        logger.info("Redis connection pool disconnected.")
