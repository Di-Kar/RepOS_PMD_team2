import logging
from typing import List

from backoff_utils import backoff
from config import ElasticsearchSettings
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError
from elasticsearch.exceptions import ConnectionTimeout, TransportError
from elasticsearch.helpers import bulk
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MOVIES_INDEX_SETTINGS = {
    "settings": {
        "refresh_interval": "1s",
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "english_possessive_stemmer": {"type": "stemmer", "language": "possessive_english"},
                "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                "russian_stemmer": {"type": "stemmer", "language": "russian"},
            },
            "analyzer": {
                "ru_en": {
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                        "english_possessive_stemmer",
                        "russian_stop",
                        "russian_stemmer",
                    ],
                }
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "imdb_rating": {"type": "float"},
            "genres": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"},
                },
            },
            "title": {
                "type": "text",
                "analyzer": "ru_en",
                "fields": {"raw": {"type": "keyword"}},
            },
            "description": {"type": "text", "analyzer": "ru_en"},
            "directors_names": {"type": "text", "analyzer": "ru_en"},
            "actors_names": {"type": "text", "analyzer": "ru_en"},
            "writers_names": {"type": "text", "analyzer": "ru_en"},
            "directors": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"},
                },
            },
            "actors": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"},
                },
            },
            "writers": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"},
                },
            },
        },
    },
}

GENRES_INDEX_SETTINGS = {
    "settings": {
        "refresh_interval": "1s",
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "english_possessive_stemmer": {"type": "stemmer", "language": "possessive_english"},
                "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                "russian_stemmer": {"type": "stemmer", "language": "russian"},
            },
            "analyzer": {
                "ru_en": {
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                        "english_possessive_stemmer",
                        "russian_stop",
                        "russian_stemmer",
                    ],
                }
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "name": {
                "type": "text",
                "analyzer": "ru_en",
                "fields": {"raw": {"type": "keyword"}},
            },
            "description": {"type": "text", "analyzer": "ru_en"},
        },
    },
}

PERSONS_INDEX_SETTINGS = {
    "settings": {
        "refresh_interval": "1s",
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "english_possessive_stemmer": {"type": "stemmer", "language": "possessive_english"},
                "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                "russian_stemmer": {"type": "stemmer", "language": "russian"},
            },
            "analyzer": {
                "ru_en": {
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                        "english_possessive_stemmer",
                        "russian_stop",
                        "russian_stemmer",
                    ],
                }
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "full_name": {
                "type": "text",
                "analyzer": "ru_en",
                "fields": {"raw": {"type": "keyword"}},
            },
            "films": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "uuid": {"type": "keyword"},
                    "roles": {"type": "keyword"},
                },
            },
        },
    },
}

_ES_EXCEPTIONS = (ESConnectionError, TransportError, ConnectionTimeout)


class ElasticsearchLoader:
    def __init__(self, settings: ElasticsearchSettings):
        self.settings = settings
        self.movies_index_name = settings.movies_index_name
        self.genres_index_name = settings.genres_index_name
        self.persons_index_name = settings.persons_index_name
        self._client: Elasticsearch | None = None

    def _get_client(self) -> Elasticsearch:
        if self._client is None:
            self._client = Elasticsearch(
                self.settings.url,
                request_timeout=30,
            )
        return self._client

    @backoff(exceptions=_ES_EXCEPTIONS)
    def ensure_index(self, index_name: str, index_settings: dict) -> None:
        """Создаёт индекс, если он не существует."""
        client = self._get_client()
        if not client.indices.exists(index=index_name):
            client.indices.create(
                index=index_name,
                settings=index_settings['settings'],
                mappings=index_settings['mappings'],
            )
            logger.info('Создан индекс %s', index_name)
        else:
            logger.debug('Индекс %s уже существует', index_name)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def bulk_upsert(self, docs: List[BaseModel], index_name: str) -> None:
        """Отправляет документы в ES через bulk API.

        Выбрасывает RuntimeError, если хотя бы один документ не был принят —
        это не позволит ETL продвинуть курсор состояния.
        """
        if not docs:
            return

        client = self._get_client()
        actions = [
            {
                '_index': index_name,
                '_id': str(doc.id),
                '_source': doc.model_dump(mode='json'),
            }
            for doc in docs
        ]

        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)

        if errors:
            logger.error(
                'Ошибки при bulk-загрузке в %s: %d из %d документов не приняты. Первые 3: %s',
                index_name, len(errors), len(docs), errors[:3],
            )
            raise RuntimeError(
                f'Bulk-загрузка в {index_name} завершилась с {len(errors)} ошибками из {len(docs)} документов'
            )

        logger.info('Проиндексировано %d документов в %s', success, index_name)
