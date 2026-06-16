from functools import lru_cache
from typing import Optional

from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from redis.asyncio import Redis

from core.config import settings
from db.elastic_db import get_elastic
from db.redis_db import get_redis
from models.film import Film
from services.base import BaseService

import logging

logger = logging.getLogger(__name__)


class FilmService(BaseService[Film]):
    index = settings.es_movies_index
    cache_prefix = 'film'
    model = Film

    def _build_list_query(self, genre: Optional[str] = None, **_) -> dict:
        if genre:
            return {'nested': {'path': 'genres', 'query': {'term': {'genres.id': genre}}}}
        return {'match_all': {}}

    def _build_search_query(self, query: str) -> dict:
        return {'multi_match': {'query': query, 'fields': ['title', 'description']}}

    @staticmethod
    def _parse_sort(sort: Optional[str]) -> list[dict]:
        if not sort:
            return [{'imdb_rating': {'order': 'desc'}}]
        field = sort.lstrip('-')
        order = 'desc' if sort.startswith('-') else 'asc'
        return [{field: {'order': order}}]

    async def get_list(
        self,
        sort: Optional[str],
        genre: Optional[str],
        page_number: int,
        page_size: int,
    ) -> list[Film]:
        key = self._build_cache_key('list', str(sort), str(genre), str(page_number), str(page_size))
        cached = await self._get_list_from_cache(key)
        if cached is not None:
            return cached
        films = await self._execute_elastic_search(
            self._build_list_query(genre=genre),
            sort=self._parse_sort(sort),
            page_number=page_number,
            page_size=page_size,
        )
        if films:
            await self._put_list_to_cache(key, films)
        return films

    async def search(self, query: str, page_number: int, page_size: int) -> list[Film]:
        key = self._build_cache_key('search', query, str(page_number), str(page_size))
        cached = await self._get_list_from_cache(key)
        if cached is not None:
            return cached
        films = await self._execute_elastic_search(
            self._build_search_query(query),
            page_number=page_number,
            page_size=page_size,
        )
        if films:
            await self._put_list_to_cache(key, films)
        return films


@lru_cache()
def get_film_service(
        redis: Redis = Depends(get_redis),
        elastic: AsyncElasticsearch = Depends(get_elastic),
) -> FilmService:
    return FilmService(redis, elastic)
