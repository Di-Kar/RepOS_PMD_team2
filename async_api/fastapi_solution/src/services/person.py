from functools import lru_cache
from typing import Optional

from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from redis.asyncio import Redis

from core.config import settings
from db.elastic_db import get_elastic
from db.redis_db import get_redis
from models.person import PersonES, PersonFilmES
from services.base import BaseService


class PersonService(BaseService[PersonES]):
    index = settings.es_persons_index
    cache_prefix = 'person'
    model = PersonES

    async def get_by_id(self, entity_id: str) -> Optional[PersonES]:
        key = f'{self.cache_prefix}:{entity_id}'
        entity = await self._get_from_cache(key)
        if entity:
            return entity
        entity = await self._get_from_elastic(entity_id)
        if not entity:
            return None
        entity.films = await self._get_person_films(entity_id)
        await self._put_to_cache(key, entity)
        return entity

    async def _get_person_films(self, person_id: str) -> list[PersonFilmES]:
        body = {
            'query': {
                'bool': {
                    'should': [
                        {'nested': {'path': 'actors', 'query': {'term': {'actors.id': person_id}}}},
                        {'nested': {'path': 'directors', 'query': {'term': {'directors.id': person_id}}}},
                        {'nested': {'path': 'writers', 'query': {'term': {'writers.id': person_id}}}},
                    ],
                    'minimum_should_match': 1,
                }
            },
            'size': 1000,
            '_source': ['id', 'actors', 'directors', 'writers'],
        }
        result = await self.elastic.search(index=settings.es_movies_index, body=body)
        films = []
        for hit in result['hits']['hits']:
            src = hit['_source']
            film_id = src['id']
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
        cache_key = f'persons:search:{query}:{page_number}:{page_size}'
        cached = await self._get_list_from_cache(cache_key)
        if cached is not None:
            return cached

        body = {
            'query': {'multi_match': {'query': query, 'fields': ['full_name']}},
            'from': (page_number - 1) * page_size,
            'size': page_size,
        }
        result = await self.elastic.search(index=self.index, body=body)
        persons = []
        for hit in result['hits']['hits']:
            person = PersonES(**hit['_source'])
            person.films = await self._get_person_films(str(person.id))
            persons.append(person)

        await self._put_list_to_cache(cache_key, persons)
        return persons

    async def get_films_by_person(self, person_id: str) -> list[dict] | None:
        person = await self._get_from_elastic(person_id)
        if not person:
            return None

        body = {
            'query': {
                'bool': {
                    'should': [
                        {'nested': {'path': 'actors', 'query': {'term': {'actors.id': person_id}}}},
                        {'nested': {'path': 'directors', 'query': {'term': {'directors.id': person_id}}}},
                        {'nested': {'path': 'writers', 'query': {'term': {'writers.id': person_id}}}},
                    ],
                    'minimum_should_match': 1,
                }
            },
            'size': 1000,
            '_source': ['id', 'title', 'imdb_rating'],
        }
        result = await self.elastic.search(index=settings.es_movies_index, body=body)
        return [
            {
                'uuid': hit['_source']['id'],
                'title': hit['_source'].get('title', ''),
                'imdb_rating': hit['_source'].get('imdb_rating'),
            }
            for hit in result['hits']['hits']
        ]


@lru_cache()
def get_person_service(
        redis: Redis = Depends(get_redis),
        elastic: AsyncElasticsearch = Depends(get_elastic),
) -> PersonService:
    return PersonService(redis, elastic)
