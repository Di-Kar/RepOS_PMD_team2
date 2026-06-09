from functools import lru_cache

from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from redis.asyncio import Redis

from core.config import settings
from db.elastic_db import get_elastic
from db.redis_db import get_redis
from models.film import Genre
from services.base import BaseService


class GenreService(BaseService[Genre]):
    index = settings.es_genres_index
    cache_prefix = 'genre'
    model = Genre

    async def get_list(self) -> list[Genre]:
        cache_key = 'genres:all'
        cached = await self._get_list_from_cache(cache_key)
        if cached is not None:
            return cached

        result = await self.elastic.search(
            index=self.index,
            body={'query': {'match_all': {}}, 'size': 1000},
        )
        genres = [Genre(**hit['_source']) for hit in result['hits']['hits']]

        await self._put_list_to_cache(cache_key, genres)
        return genres


@lru_cache()
def get_genre_service(
        redis: Redis = Depends(get_redis),
        elastic: AsyncElasticsearch = Depends(get_elastic),
) -> GenreService:
    return GenreService(redis, elastic)
