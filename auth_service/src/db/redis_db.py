"""
Redis database connection module.
Provides async Redis client and token/cache management utilities.
"""

from typing import Optional

from redis.asyncio import Redis, ConnectionPool
from src.core.config import settings


# Create connection pool
redis_pool: Optional[ConnectionPool] = None

# Global Redis client instance
redis_client: Optional[Redis] = None


async def get_redis_pool() -> ConnectionPool:
    """
    Get or create Redis connection pool.

    Returns:
        ConnectionPool: Redis connection pool
    """
    global redis_pool

    if redis_pool is None:
        redis_pool = ConnectionPool.from_url(
            settings.redis_dsn,
            decode_responses=True,  # Automatically decode responses to strings
            max_connections=50,
            retry_on_timeout=True,
        )

    return redis_pool


async def get_redis() -> Redis:
    """
    Dependency function that provides Redis client.

    Returns:
        Redis: Redis client instance
    """
    pool = await get_redis_pool()
    return Redis(connection_pool=pool)


async def init_redis() -> None:
    """
    Initialize Redis connection.

    Should be called on application startup.
    """
    global redis_client

    pool = await get_redis_pool()
    redis_client = Redis(connection_pool=pool)

    # Test connection
    await redis_client.ping()


async def close_redis() -> None:
    """
    Close Redis connections.

    Should be called on application shutdown.
    """
    global redis_client, redis_pool

    if redis_client:
        await redis_client.close()
        redis_client = None

    if redis_pool:
        await redis_pool.disconnect()
        redis_pool = None