"""Загрузка данных в Elasticsearch."""
import logging
from typing import Any, Dict, List
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import NotFoundError

logger = logging.getLogger(__name__)

INDEX_MAPPING = {
    "settings": {
        "refresh_interval": "1s",
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "english_possessive_stemmer": {"type": "stemmer", "language": "possessive_english"},
                "russian_stop": {"type": "stop", "stopwords": "_russian_"},
                "russian_stemmer": {"type": "stemmer", "language": "russian"}
            },
            "analyzer": {
                "ru_en": {
                    "tokenizer": "standard",
                    "filter": [
                        "lowercase", "english_stop", "english_stemmer",
                        "english_possessive_stemmer", "russian_stop", "russian_stemmer"
                    ]
                }
            }
        }
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "imdb_rating": {"type": "float"},
            "genres": {"type": "keyword"},
            "title": {
                "type": "text", "analyzer": "ru_en", "fields": {
                    "raw": {"type": "keyword"}
                }
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
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            },
            "actors": { 
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            },
            "writers": {
                "type": "nested",
                "dynamic": "strict",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "ru_en"}
                }
            }
        }
    }
}


class ElasticsearchLoader:
    def __init__(self, dsn: str, index_name: str):
        self.es = Elasticsearch(dsn, request_timeout=30, retry_on_timeout=True)
        self.index_name = index_name

    def create_index_if_not_exists(self) -> bool:
        try:
            if self.es.indices.exists(index=self.index_name):
                return False
            self.es.indices.create(index=self.index_name, **INDEX_MAPPING)
            logger.info(f" Индекс '{self.index_name}' создан.")
            return True
        except Exception as e:
            logger.error(f" Ошибка индекса: {e}", exc_info=True)
            raise

    def load_documents(self, documents: List[Dict[str, Any]], chunk_size: int) -> None:
        if not documents: return
        
        actions = [
            {"_op_type": "index", "_index": self.index_name, "_id": doc["_id"], 
             "_source": {k: v for k, v in doc.items() if k != "_id"}}
            for doc in documents
        ]
        helpers.bulk(self.es, actions, chunk_size=chunk_size, raise_on_error=True)
        logger.info(f" Загружено {len(actions)} документов.")