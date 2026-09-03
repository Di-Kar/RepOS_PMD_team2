import os
from logging import config as logging_config

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.logger import LOGGING

logging_config.dictConfig(LOGGING)

# Фиксировано именем сервиса в docker-compose.yml, не читается из env.
AUTH_SERVICE_URL = 'http://auth_service:8000/api/v1/auth'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    project_name: str = 'movies'

    es_movies_index: str = Field(default='movies', alias='ES_MOVIES_INDEX_NAME')
    es_persons_index: str = Field(default='persons', alias='ES_PERSONS_INDEX_NAME')
    es_genres_index: str = Field(default='genres', alias='ES_GENRES_INDEX_NAME')

    redis_host: str = '127.0.0.1'
    redis_port: int = 6379

    elastic_host: str = Field(default='127.0.0.1', alias='ES_HOST')
    elastic_port: int = Field(default=9200, alias='ES_PORT')
    elastic_schema: str = 'http://'

    auth_request_timeout: float = Field(default=1.5, alias='AUTH_REQUEST_TIMEOUT')

    # Пусто = Sentry отключён (DSN создаётся в проекте на sentry.io)
    sentry_dsn: str = Field(default='', alias='SENTRY_DSN')
    debug: bool = Field(default=False, alias='DEBUG')

    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


settings = Settings()
