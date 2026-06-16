import json
import logging
from typing import Generic, Optional, TypeVar

from elasticsearch import AsyncElasticsearch, NotFoundError
from pydantic import BaseModel
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

ModelType = TypeVar('ModelType', bound=BaseModel)

CACHE_EXPIRE_IN_SECONDS = 60 * 5


class BaseService(Generic[ModelType]):
    index: str
    cache_prefix: str
    model: type[ModelType]

    def __init__(self, redis: Redis, elastic: AsyncElasticsearch):
        self.redis = redis
        self.elastic = elastic

    # --- Формирование ключа кэша ---

    def _build_cache_key(self, *parts: str) -> str:
        return ':'.join([self.cache_prefix, *[str(p) for p in parts]])

    # --- Получение одного объекта ---

    async def get_by_id(self, entity_id: str) -> Optional[ModelType]:
        key = self._build_cache_key(entity_id)
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

    # --- Построение запросов (переопределяются в наследниках) ---

    def _build_list_query(self, **kwargs) -> dict:
        return {'match_all': {}}

    def _build_search_query(self, query: str) -> dict:
        raise NotImplementedError(f'{self.__class__.__name__} does not implement _build_search_query')

    # --- Выполнение поиска в Elasticsearch ---

    async def _execute_elastic_search(
        self,
        query: dict,
        sort: Optional[list] = None,
        page_number: int = 1,
        page_size: int = 50,
    ) -> list[ModelType]:
        body: dict = {
            'query': query,
            'from': (page_number - 1) * page_size,
            'size': page_size,
        }
        if sort:
            body['sort'] = sort
        try:
            result = await self.elastic.search(index=self.index, body=body)
        except Exception as e:
            logger.warning(f"Elasticsearch search failed in {self.__class__.__name__}: {e}")
            return []
        items = []
        for hit in result['hits']['hits']:
            try:
                items.append(self.model(**hit['_source']))
            except Exception as e:
                logger.warning(f"Failed to parse ES hit in {self.__class__.__name__}: {e}")
        return items

    # --- Кэш: одиночный объект ---

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
            await self.redis.set(key, obj.model_dump_json(), ex=CACHE_EXPIRE_IN_SECONDS)
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")

    # --- Кэш: список объектов ---

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
                ex=CACHE_EXPIRE_IN_SECONDS,
            )
        except Exception as e:
            logger.warning(f"Redis SET failed for key='{key}': {e}")
