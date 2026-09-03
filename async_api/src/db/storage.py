import logging
from abc import ABC, abstractmethod
from typing import Optional

from core.backoff import ExponentialBackoffRetryPolicy, RetryPolicy
from core.exceptions import StorageUnavailableError
from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch import ConnectionTimeout as ESConnectionTimeout
from fastapi import Depends

from db.elastic_db import get_elastic

logger = logging.getLogger(__name__)

_ES_RETRY_POLICY = ExponentialBackoffRetryPolicy(
    retryable_exceptions=(ESConnectionError, ESConnectionTimeout),
    attempts=3,
    min_wait=0.5,
    max_wait=8.0,
)


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
    Политика повторных попыток инжектируется через конструктор (DIP).
    """

    def __init__(
        self, elastic: AsyncElasticsearch, retry_policy: RetryPolicy = _ES_RETRY_POLICY
    ):
        self._elastic = elastic
        self._retry = retry_policy

    async def get(self, index: str, doc_id: str) -> Optional[dict]:
        try:
            doc = await self._retry.call(self._elastic.get, index=index, id=doc_id)
        except NotFoundError:
            return None
        except (ESConnectionError, ESConnectionTimeout) as e:
            logger.error(
                f"Elasticsearch unavailable on GET index='{index}' id='{doc_id}': {e}"
            )
            raise StorageUnavailableError('Elasticsearch is unavailable') from e
        return doc.get('_source')

    async def search(self, index: str, body: dict) -> list[dict]:
        try:
            result = await self._retry.call(
                self._elastic.search, index=index, body=body
            )
        except (ESConnectionError, ESConnectionTimeout) as e:
            logger.error(f"Elasticsearch unavailable on search index='{index}': {e}")
            raise StorageUnavailableError('Elasticsearch is unavailable') from e
        hits = result.get('hits', {}).get('hits', [])
        return [hit['_source'] for hit in hits if '_source' in hit]


def get_storage(elastic: AsyncElasticsearch = Depends(get_elastic)) -> AbstractStorage:
    # Зависимость FastAPI: отдаёт абстракцию, конкретную реализацию строим здесь
    return ElasticStorage(elastic)
