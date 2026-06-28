import logging
from typing import Generic, Optional, TypeVar

from elasticsearch import AsyncElasticsearch, NotFoundError
from pydantic import BaseModel

from cache.interface import CacheInterface

logger = logging.getLogger(__name__)

ModelType = TypeVar('ModelType', bound=BaseModel)

CACHE_EXPIRE_IN_SECONDS = 60 * 5


class BaseService(Generic[ModelType]):
    index: str
    cache_prefix: str
    model: type[ModelType]
    cache: CacheInterface[ModelType]

    def __init__(
        self,
        elastic: AsyncElasticsearch,
        cache: CacheInterface[ModelType],
    ):
        self.elastic = elastic
        self.cache = cache

    # --- Формирование ключа кэша ---

    def _build_cache_key(self, *parts: str) -> str:
        return ':'.join([self.cache_prefix, *[str(p) for p in parts]])

    # --- Получение одного объекта ---

    async def get_by_id(self, entity_id: str) -> Optional[ModelType]:
        key = self._build_cache_key(entity_id)
        entity = await self.cache.get(key)
        if not entity:
            entity = await self._get_from_elastic(entity_id)
            if not entity:
                return None
            await self.cache.set(key, entity, CACHE_EXPIRE_IN_SECONDS)
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

    # --- Списки объектов через cache_service ---

    async def _get_list_from_cache(self, key: str) -> Optional[list[ModelType]]:
        return await self.cache.get_list(key)

    async def _put_list_to_cache(self, key: str, items: list[ModelType]) -> None:
        await self.cache.set_list(key, items, CACHE_EXPIRE_IN_SECONDS)
