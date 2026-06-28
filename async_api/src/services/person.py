from functools import lru_cache
from typing import Optional

from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from redis.asyncio import Redis

from cache.redis_cache import RedisCache
from core.config import settings
from db.elastic_db import get_elastic
from db.redis_db import get_redis
from models.person import PersonES, PersonFilmES
from services.base import BaseService
import logging

logger = logging.getLogger(__name__)


class PersonService(BaseService[PersonES]):
    index = settings.es_persons_index
    cache_prefix = 'person'
    model = PersonES

    def _build_search_query(self, query: str) -> dict:
        return {'multi_match': {'query': query, 'fields': ['full_name']}}

    async def get_by_id(self, entity_id: str) -> Optional[PersonES]:
        key = self._build_cache_key(entity_id)
        entity = await self.cache.get(key)
        if entity:
            return entity

        entity = await self._get_from_elastic(entity_id)
        if not entity:
            return None

        try:
            entity.films = await self._get_person_films(entity_id)
        except Exception as e:
            logger.warning(f"Failed to fetch films for person id='{entity_id}': {e}")
            entity.films = []

        await self.cache.set(key, entity, 60 * 5)
        return entity

    async def _get_person_films(self, person_id: str) -> list[PersonFilmES]:
        query = {
            'bool': {
                'should': [
                    {'nested': {'path': 'actors', 'query': {'term': {'actors.id': person_id}}}},
                    {'nested': {'path': 'directors', 'query': {'term': {'directors.id': person_id}}}},
                    {'nested': {'path': 'writers', 'query': {'term': {'writers.id': person_id}}}},
                ],
                'minimum_should_match': 1,
            }
        }
        try:
            result = await self.elastic.search(
                index=settings.es_movies_index,
                body={'query': query, 'size': 1000, '_source': ['id', 'actors', 'directors', 'writers']},
            )
        except Exception as e:
            logger.warning(f"Elasticsearch search failed for person films id='{person_id}': {e}")
            return []

        films = []
        for hit in result.get('hits', {}).get('hits', []):
            src = hit.get('_source') or {}
            film_id = src.get('id')
            if not film_id:
                continue
            roles = []
            if any(a.get('id') == person_id for a in src.get('actors', [])):
                roles.append('actor')
            if any(d.get('id') == person_id for d in src.get('directors', [])):
                roles.append('director')
            if any(w.get('id') == person_id for w in src.get('writers', [])):
                roles.append('writer')
            films.append(PersonFilmES(uuid=film_id, roles=roles))
        return films

    async def search(self, query: str, page_number: int, page_size: int) -> list[PersonES]:
        key = self._build_cache_key('search', query, str(page_number), str(page_size))
        cached = await self._get_list_from_cache(key)
        if cached is not None:
            return cached
        persons = await self._execute_elastic_search(
            self._build_search_query(query),
            page_number=page_number,
            page_size=page_size,
        )
        if persons:
            await self._put_list_to_cache(key, persons)
        return persons

    async def get_films_by_person(self, person_id: str) -> list[dict] | None:
        person = await self._get_from_elastic(person_id)
        if not person:
            return None

        query = {
            'bool': {
                'should': [
                    {'nested': {'path': 'actors', 'query': {'term': {'actors.id': person_id}}}},
                    {'nested': {'path': 'directors', 'query': {'term': {'directors.id': person_id}}}},
                    {'nested': {'path': 'writers', 'query': {'term': {'writers.id': person_id}}}},
                ],
                'minimum_should_match': 1,
            }
        }
        try:
            result = await self.elastic.search(
                index=settings.es_movies_index,
                body={'query': query, 'size': 1000, '_source': ['id', 'title', 'imdb_rating']},
            )
        except Exception as e:
            logger.warning(f"Elasticsearch search failed for person films id='{person_id}': {e}")
            return []

        return [
            {
                'uuid': hit.get('_source', {}).get('id', ''),
                'title': hit.get('_source', {}).get('title', ''),
                'imdb_rating': hit.get('_source', {}).get('imdb_rating'),
            }
            for hit in result.get('hits', {}).get('hits', [])
        ]


@lru_cache()
def get_person_service(
        redis: Redis = Depends(get_redis),
        elastic: AsyncElasticsearch = Depends(get_elastic),
) -> PersonService:
    cache = RedisCache(redis, PersonES)
    return PersonService(elastic, cache)
