import json
from typing import Generic, Optional, TypeVar

from elasticsearch import AsyncElasticsearch, NotFoundError
from pydantic import BaseModel
from redis.asyncio import Redis

ModelType = TypeVar('ModelType', bound=BaseModel)

CACHE_EXPIRE_IN_SECONDS = 60 * 5  # 5 минут


class BaseService(Generic[ModelType]):
    index: str
    cache_prefix: str
    model: type[ModelType]

    def __init__(self, redis: Redis, elastic: AsyncElasticsearch):
        self.redis = redis
        self.elastic = elastic

    async def get_by_id(self, entity_id: str) -> Optional[ModelType]:
        key = f'{self.cache_prefix}:{entity_id}'
        entity = await self._get_from_cache(key)
        if not entity:
            entity = await self._get_from_elastic(entity_id)
            if not entity:
                return None
            await self._put_to_cache(key, entity)
        return entity

    async def _get_from_elastic(self, entity_id: str) -> Optional[ModelType]:
        try:
            doc = await self.elastic.get(index=self.index, id=entity_id)
        except NotFoundError:
            return None
        return self.model(**doc['_source'])

    async def _get_from_cache(self, key: str) -> Optional[ModelType]:
        data = await self.redis.get(key)
        if not data:
            return None
        return self.model.model_validate_json(data)

    async def _put_to_cache(self, key: str, obj: ModelType) -> None:
        await self.redis.set(key, obj.model_dump_json(), CACHE_EXPIRE_IN_SECONDS)

    async def _get_list_from_cache(self, key: str) -> Optional[list[ModelType]]:
        cached = await self.redis.get(key)
        if not cached:
            return None
        return [self.model.model_validate(item) for item in json.loads(cached)]

    async def _put_list_to_cache(self, key: str, items: list[ModelType]) -> None:
        await self.redis.set(
            key,
            json.dumps([item.model_dump(mode='json') for item in items]),
            CACHE_EXPIRE_IN_SECONDS,
        )
