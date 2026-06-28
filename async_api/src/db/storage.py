import logging
from abc import ABC, abstractmethod
from typing import Optional

from elasticsearch import AsyncElasticsearch, NotFoundError
from fastapi import Depends

from db.elastic_db import get_elastic

logger = logging.getLogger(__name__)


class AbstractStorage(ABC):
    """Абстрактное хранилище документов (только чтение).

    Сервисы зависят от этого интерфейса, а не от конкретной БД,
    поэтому реализацию (Elasticsearch и т. п.) можно подменить
    без изменения сервисного слоя (принципы DIP и OCP).
    """

    @abstractmethod
    async def get(self, index: str, doc_id: str) -> Optional[dict]:
        """Вернуть тело документа (_source) по id или None, если не найден."""

    @abstractmethod
    async def search(self, index: str, body: dict) -> list[dict]:
        """Выполнить поиск и вернуть список тел найденных документов (_source)."""


class ElasticStorage(AbstractStorage):
    """Реализация хранилища поверх Elasticsearch.

    Инкапсулирует работу с клиентом ES и обработку ошибок,
    наружу отдаёт только сырые данные документов.
    """

    def __init__(self, elastic: AsyncElasticsearch):
        self._elastic = elastic

    async def get(self, index: str, doc_id: str) -> Optional[dict]:
        try:
            doc = await self._elastic.get(index=index, id=doc_id)
        except NotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Elasticsearch GET failed for index='{index}' id='{doc_id}': {e}")
            return None
        return doc.get('_source')

    async def search(self, index: str, body: dict) -> list[dict]:
        try:
            result = await self._elastic.search(index=index, body=body)
        except Exception as e:
            logger.warning(f"Elasticsearch search failed for index='{index}': {e}")
            return []
        hits = result.get('hits', {}).get('hits', [])
        return [hit['_source'] for hit in hits if '_source' in hit]


def get_storage(elastic: AsyncElasticsearch = Depends(get_elastic)) -> AbstractStorage:
    # Зависимость FastAPI: отдаёт абстракцию, конкретную реализацию строим здесь
    return ElasticStorage(elastic)
