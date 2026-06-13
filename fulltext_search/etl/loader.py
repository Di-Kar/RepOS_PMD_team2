import logging
from typing import List
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError, TransportError, ConnectionTimeout
from elasticsearch.helpers import bulk
from backoff_utils import backoff
from config import ElasticsearchSettings
from models import Genre, Movie, Person

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
    def ensure_movies_index(self) -> None:
        """Создаёт индекс фильмов, если он не существует."""
        client = self._get_client()
        if not client.indices.exists(index=self.movies_index_name):
            client.indices.create(
                index=self.movies_index_name,
                settings=MOVIES_INDEX_SETTINGS['settings'],
                mappings=MOVIES_INDEX_SETTINGS['mappings'],
            )
            logger.info('Создан индекс %s', self.movies_index_name)
        else:
            logger.debug('Индекс %s уже существует', self.movies_index_name)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def ensure_genres_index(self) -> None:
        """Создаёт индекс жанров, если он не существует."""
        client = self._get_client()
        if not client.indices.exists(index=self.genres_index_name):
            client.indices.create(
                index=self.genres_index_name,
                settings=GENRES_INDEX_SETTINGS['settings'],
                mappings=GENRES_INDEX_SETTINGS['mappings'],
            )
            logger.info('Создан индекс %s', self.genres_index_name)
        else:
            logger.debug('Индекс %s уже существует', self.genres_index_name)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def bulk_upsert_genres(self, genres: List[Genre]) -> None:
        """Отправляет жанры в ES через bulk API.

        Выбрасывает RuntimeError, если хотя бы один документ не был принят —
        это не позволит ETL продвинуть курсор состояния.
        """
        if not genres:
            return

        client = self._get_client()
        actions = [
            {
                '_index': self.genres_index_name,
                '_id': str(genre.id),
                '_source': genre.model_dump(mode='json'),
            }
            for genre in genres
        ]

        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)

        if errors:
            logger.error(
                'Ошибки при bulk-загрузке жанров: %d из %d документов не приняты. Первые 3: %s',
                len(errors), len(genres), errors[:3],
            )
            raise RuntimeError(
                f'Bulk-загрузка жанров завершилась с {len(errors)} ошибками из {len(genres)} документов'
            )

        logger.info('Проиндексировано %d жанров', success)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def ensure_persons_index(self) -> None:
        """Создаёт индекс персон, если он не существует."""
        client = self._get_client()
        if not client.indices.exists(index=self.persons_index_name):
            client.indices.create(
                index=self.persons_index_name,
                settings=PERSONS_INDEX_SETTINGS['settings'],
                mappings=PERSONS_INDEX_SETTINGS['mappings'],
            )
            logger.info('Создан индекс %s', self.persons_index_name)
        else:
            logger.debug('Индекс %s уже существует', self.persons_index_name)

    @backoff(exceptions=_ES_EXCEPTIONS)
    def bulk_upsert_persons(self, persons: List[Person]) -> None:
        """Отправляет персон в ES через bulk API.

        Выбрасывает RuntimeError, если хотя бы один документ не был принят —
        это не позволит ETL продвинуть курсор состояния.
        """
        if not persons:
            return

        client = self._get_client()
        actions = [
            {
                '_index': self.persons_index_name,
                '_id': str(person.id),
                '_source': person.model_dump(mode='json'),
            }
            for person in persons
        ]

        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)

        if errors:
            logger.error(
                'Ошибки при bulk-загрузке персон: %d из %d документов не приняты. Первые 3: %s',
                len(errors), len(persons), errors[:3],
            )
            raise RuntimeError(
                f'Bulk-загрузка персон завершилась с {len(errors)} ошибками из {len(persons)} документов'
            )

        logger.info('Проиндексировано %d персон', success)

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
                '_index': self.movies_index_name,
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
