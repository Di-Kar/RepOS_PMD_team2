import logging
from typing import List
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError, TransportError, ConnectionTimeout
from elasticsearch.helpers import bulk
from backoff_utils import backoff
from config import ElasticsearchSettings
from models import Movie

logger = logging.getLogger(__name__)

INDEX_SETTINGS = {
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
            "genres": {"type": "keyword"},
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

_ES_EXCEPTIONS = (ESConnectionError, TransportError, ConnectionTimeout)


class ElasticsearchLoader:
    def __init__(self, settings: ElasticsearchSettings):
        self.settings = settings
        self.index_name = settings.index_name
        self._client: Elasticsearch | None = None

    def _get_client(self) -> Elasticsearch:
        if self._client is None:
            self._client = Elasticsearch(
                self.settings.url,
                request_timeout=30,
            )
        return self._client

    @backoff(exceptions=_ES_EXCEPTIONS)
    def ensure_index(self) -> None:
        """Создаёт индекс, если он не существует."""
        client = self._get_client()
        if not client.indices.exists(index=self.index_name):
            client.indices.create(
                index=self.index_name,
                settings=INDEX_SETTINGS['settings'],
                mappings=INDEX_SETTINGS['mappings'],
            )
            logger.info('Создан индекс %s', self.index_name)
        else:
            logger.debug('Индекс %s уже существует', self.index_name)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def bulk_upsert(self, movies: List[Movie]) -> None:
        """Отправляет фильмы в ES через bulk API.

        Выбрасывает RuntimeError, если хотя бы один документ не был принят —
        это не позволит ETL продвинуть курсор состояния.
        """
        if not movies:
            return

        client = self._get_client()
        actions = [
            {
                '_index': self.index_name,
                '_id': str(movie.id),
                '_source': movie.model_dump(mode='json'),
            }
            for movie in movies
        ]

        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)

        if errors:
            logger.error(
                'Ошибки при bulk-загрузке: %d из %d документов не приняты. Первые 3: %s',
                len(errors), len(movies), errors[:3],
            )
            raise RuntimeError(
                f'Bulk-загрузка завершилась с {len(errors)} ошибками из {len(movies)} документов'
            )

        logger.info('Проиндексировано %d фильмов', success)
