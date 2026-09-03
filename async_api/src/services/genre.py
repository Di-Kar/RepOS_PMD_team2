from functools import lru_cache

from cache.redis_cache import RedisCache
from core.config import settings
from db.redis_db import get_redis
from db.storage import AbstractStorage, get_storage
from fastapi import Depends
from models.film import Genre
from redis.asyncio import Redis

from services.base import BaseService


class GenreService(BaseService[Genre]):
    index = settings.es_genres_index
    cache_prefix = 'genre'
    model = Genre

    async def get_list(self) -> list[Genre]:
        key = self._build_cache_key('all')
        cached = await self._get_list_from_cache(key)
        if cached is not None:
            return cached
        genres = await self._execute_search({'match_all': {}}, page_size=1000)
        await self._put_list_to_cache(key, genres)
        return genres


@lru_cache
def get_genre_service(
        storage: AbstractStorage = Depends(get_storage),
        redis: Redis = Depends(get_redis),
) -> GenreService:
    cache = RedisCache(redis, Genre)
    return GenreService(storage, cache)
