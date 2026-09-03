"""Настройки функциональных тестов с вложенной структурой."""
import os
from typing import Any, Dict

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from tests.async_api.testdata.es_mapping import (
    GENRES_INDEX_SETTINGS,
    MOVIES_INDEX_SETTINGS,
    PERSONS_INDEX_SETTINGS,
)

"""Настройки тестов с автоопределением окружения."""


def is_docker() -> bool:
    """Определяет, запущен ли код в Docker."""
    if os.path.exists('/.dockerenv'):
        return True

# Вложенные BaseModel не читают переменные окружения сами (это делает только
# BaseSettings), поэтому env-переопределения из docker-compose подхватываем здесь.
DEFAULT_ES_HOST = os.getenv('ES_HOST', 'elasticsearch' if is_docker() else '127.0.0.1')
DEFAULT_REDIS_HOST = os.getenv('REDIS_HOST', 'async_api_redis' if is_docker() else '127.0.0.1')
DEFAULT_API_HOST = os.getenv('API_HOST', 'async_api' if is_docker() else '127.0.0.1')


class ElasticSettings(BaseModel):
    """Настройки Elasticsearch."""
    es_host: str = Field(default=DEFAULT_ES_HOST, alias='ES_HOST')
    es_port: int = Field(default=9200, alias='ES_PORT')
    es_index_movies: str = Field(default='movies', alias='ES_INDEX_MOVIES')
    es_index_genres: str = Field(default='genres', alias='ES_INDEX_GENRES')
    es_index_persons: str = Field(default='persons', alias='ES_INDEX_PERSONS')

    model_config = {'populate_by_name': True, 'extra': 'ignore'}

    def get_host(self) -> str:
        """Возвращает полный URL для подключения к ES."""
        return f"http://{self.es_host}:{self.es_port}"


class RedisSettings(BaseModel):
    """Настройки Redis."""
    host: str = Field(default=DEFAULT_REDIS_HOST, alias='REDIS_HOST')
    port: int = Field(default=6379, alias='REDIS_PORT')

    model_config = {'populate_by_name': True, 'extra': 'ignore'}


class FastAPISettings(BaseModel):
    """Настройки FastAPI-сервиса."""
    api_host: str = Field(default=DEFAULT_API_HOST, alias='API_HOST')
    api_port: int = Field(default=8000, alias='API_PORT')

    model_config = {'populate_by_name': True, 'extra': 'ignore'}

    def get_host(self) -> str:
        """Возвращает полный URL API."""
        return f"http://{self.api_host}:{self.api_port}"


class TestSettings(BaseSettings):
    """Главный класс настроек тестов."""
    elastic_settings: ElasticSettings = Field(default_factory=ElasticSettings)
    redis_settings: RedisSettings = Field(default_factory=RedisSettings)
    fastapi_settings: FastAPISettings = Field(default_factory=FastAPISettings)
    
    http_timeout: float = Field(default=5.0, alias='HTTP_TIMEOUT')

    model_config = {
        'env_file': '.env.test',
        'env_file_encoding': 'utf-8',
        'extra': 'ignore',
        'populate_by_name': True,
    }

    def es_index_mapping(self, index_name: str) -> Dict[str, Any]:
        """Возвращает маппинг для указанного индекса."""
        mapping = {
            'movies': MOVIES_INDEX_SETTINGS,
            'genres': GENRES_INDEX_SETTINGS,
            'persons': PERSONS_INDEX_SETTINGS,
        }
        if index_name not in mapping:
            raise ValueError(f"Неизвестный индекс: {index_name}")
        return mapping[index_name]


test_settings = TestSettings()


def print_settings() -> None:
    """Выводит текущие настройки (для отладки)."""
    print("=" * 60)
    print("📋 Текущие настройки тестов:")
    print("=" * 60)
    print(f"Elasticsearch: {test_settings.elastic_settings.get_host()}")
    print(f"  - Индекс фильмов: {test_settings.elastic_settings.es_index_movies}")
    print(f"  - Индекс жанров:  {test_settings.elastic_settings.es_index_genres}")
    print(f"  - Индекс персон:  {test_settings.elastic_settings.es_index_persons}")
    print(f"Redis: {test_settings.redis_settings.host}:{test_settings.redis_settings.port}")
    print(f"API: {test_settings.fastapi_settings.get_host()}")
    print("=" * 60)


if __name__ == '__main__':
    print_settings()
