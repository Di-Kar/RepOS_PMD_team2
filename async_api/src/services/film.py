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

    async def get_list(
        self,
        sort: Optional[str],
        genre: Optional[str],
        page_number: int,
        page_size: int,
    ) -> list[Film]:
        cache_key = f'films:list:{sort}:{genre}:{page_number}:{page_size}'
        cached = await self._get_list_from_cache(cache_key)
        if cached is not None:
            return cached

        query: dict = {'match_all': {}}
        if genre:
            query = {'nested': {'path': 'genres', 'query': {'term': {'genres.id': genre}}}}

        sort_field = 'imdb_rating'
        sort_order = 'desc'
        if sort:
            if sort.startswith('-'):
                sort_field = sort[1:]
                sort_order = 'desc'
            else:
                sort_field = sort
                sort_order = 'asc'

        body = {
            'query': query,
            'sort': [{sort_field: {'order': sort_order}}],
            'from': (page_number - 1) * page_size,
            'size': page_size,
        }
        try:
            result = await self.elastic.search(index=self.index, body=body)
        except Exception as e:
            logger.warning(f"Elasticsearch search failed for films list: {e}")
            return []
        
        films = [Film(**hit['_source']) for hit in result['hits']['hits']]
        if films:
            await self._put_list_to_cache(cache_key, films)
        return films

    async def search(self, query: str, page_number: int, page_size: int) -> list[Film]:
        cache_key = f'films:search:{query}:{page_number}:{page_size}'
        cached = await self._get_list_from_cache(cache_key)
        if cached is not None:
            return cached

        body = {
            'query': {'multi_match': {'query': query, 'fields': ['title', 'description']}},
            'from': (page_number - 1) * page_size,
            'size': page_size,
        }
        try:
            result = await self.elastic.search(index=self.index, body=body)
        except Exception as e:
            logger.warning(f"Elasticsearch search failed for query '{query}': {e}")
            return []

        films = [Film(**hit['_source']) for hit in result.get('hits', {}).get('hits', [])]
        if films:
            await self._put_list_to_cache(cache_key, films)
        return films


@lru_cache()
def get_film_service(
        redis: Redis = Depends(get_redis),
        elastic: AsyncElasticsearch = Depends(get_elastic),
) -> FilmService:
    return FilmService(redis, elastic)
