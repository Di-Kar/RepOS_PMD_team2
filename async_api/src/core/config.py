import os
from logging import config as logging_config

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.logger import LOGGING

logging_config.dictConfig(LOGGING)


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

    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


settings = Settings()
