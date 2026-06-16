import json
from typing import Generic, Optional, TypeVar

from elasticsearch import AsyncElasticsearch, NotFoundError
from pydantic import BaseModel
from redis.asyncio import Redis
import logging

logger = logging.getLogger(__name__)

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
        except Exception as e:
            logger.warning(f"Elasticsearch GET failed for id='{entity_id}': {e}")
            return None
        try:
            return self.model(**doc['_source'])
        except Exception as e:
            logger.warning(f"Failed to parse ES source for id='{entity_id}': {e}")
            return None

    async def _get_from_cache(self, key: str) -> Optional[ModelType]:
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
            return self.model.model_validate_json(data)
        except Exception as e:
            logger.warning(f"Failed to parse Redis JSON for key='{key}': {e}")
            return None

    async def _put_to_cache(self, key: str, obj: ModelType) -> None:
        if not self.redis:
            return
        try:
            await self.redis.set(key, obj.model_dump_json(), CACHE_EXPIRE_IN_SECONDS)
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")

    async def _get_list_from_cache(self, key: str) -> Optional[list[ModelType]]:
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
            return [self.model.model_validate(item) for item in json.loads(cached)]
        except Exception as e:
            logger.warning(f"Failed to parse cached list JSON for key='{key}': {e}")
            return None

    async def _put_list_to_cache(self, key: str, items: list[ModelType]) -> None:
        if not self.redis:
            return
        try:
            await self.redis.set(
                key,
                json.dumps([item.model_dump(mode='json') for item in items]),
                CACHE_EXPIRE_IN_SECONDS,
            )
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")
