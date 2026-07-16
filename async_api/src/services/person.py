from functools import lru_cache
from typing import Optional

from fastapi import Depends
from redis.asyncio import Redis

from cache.redis_cache import RedisCache
from core.config import settings
from core.exceptions import StorageUnavailableError
from db.redis_db import get_redis
from db.storage import AbstractStorage, get_storage
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

        entity = await self._get_from_storage(entity_id)
        if not entity:
            return None

        try:
            entity.films = await self._get_person_films(entity_id)
        except StorageUnavailableError:
            raise
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
        sources = await self.storage.search(
            settings.es_movies_index,
            {'query': query, 'size': 1000, '_source': ['id', 'actors', 'directors', 'writers']},
        )

        films = []
        for src in sources:
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
        persons = await self._execute_search(
            self._build_search_query(query),
            page_number=page_number,
            page_size=page_size,
        )
        await self._put_list_to_cache(key, persons)
        return persons

    async def get_films_by_person(self, person_id: str) -> list[dict] | None:
        person = await self._get_from_storage(person_id)
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
        sources = await self.storage.search(
            settings.es_movies_index,
            {'query': query, 'size': 1000, '_source': ['id', 'title', 'imdb_rating']},
        )

        return [
            {
                'uuid': src.get('id', ''),
                'title': src.get('title', ''),
                'imdb_rating': src.get('imdb_rating'),
            }
            for src in sources
        ]


@lru_cache()
def get_person_service(
        storage: AbstractStorage = Depends(get_storage),
        redis: Redis = Depends(get_redis),
) -> PersonService:
    cache = RedisCache(redis, PersonES)
    return PersonService(storage, cache)
