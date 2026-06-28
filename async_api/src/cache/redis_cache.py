import json
import logging
from typing import Generic, List, Optional, TypeVar

from redis.asyncio import Redis

from cache.interface import CacheInterface

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RedisCache(CacheInterface[T]):
    """Реализация кэша с использованием Redis. Соблюдает SRP и OCP."""

    def __init__(self, redis: Redis, model_class: type[T]):
        self.redis = redis
        self.model_class = model_class

    async def get(self, key: str) -> Optional[T]:
        """Получить одиночный объект из кэша."""
        if not self.redis:
            return None
        try:
            data = await self.redis.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed for key='{key}': {e}")
            return None
        
        if not data:
            return None
        
        try:
            return self.model_class.model_validate_json(data)
        except Exception as e:
            logger.warning(f"Failed to parse Redis JSON for key='{key}': {e}")
            return None

    async def set(self, key: str, value: T, expire: int) -> None:
        """Сохранить одиночный объект в кэш."""
        if not self.redis:
            return
        try:
            await self.redis.set(key, value.model_dump_json(), ex=expire)
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")

    async def get_list(self, key: str) -> Optional[List[T]]:
        """Получить список объектов из кэша."""
        if not self.redis:
            return None
        try:
            cached = await self.redis.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed for key='{key}': {e}")
            return None
        
        if not cached:
            return None
        
        try:
            return [self.model_class.model_validate(item) for item in json.loads(cached)]
        except Exception as e:
            logger.warning(f"Failed to parse cached list JSON for key='{key}': {e}")
            return None

    async def set_list(self, key: str, value: List[T], expire: int) -> None:
        """Сохранить список объектов в кэш."""
        if not self.redis:
            return
        try:
            await self.redis.set(
                key,
                json.dumps([item.model_dump(mode='json') for item in value]),
                ex=expire,
            )
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")

    async def delete(self, key: str) -> None:
        """Удалить объект из кэша по ключу."""
        if not self.redis:
            return
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.warning(f"Redis DELETE failed for key='{key}': {e}")

    async def delete_pattern(self, pattern: str) -> None:
        """Удалить объекты из кэша по паттерну ключа."""
        if not self.redis:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await self.redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Redis DELETE pattern failed for pattern='{pattern}': {e}")
