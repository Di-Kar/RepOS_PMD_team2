import os
from logging import config as logging_config

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.logger import LOGGING

logging_config.dictConfig(LOGGING)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    project_name: str = 'movies'

    es_movies_index: str = 'movies'
    es_persons_index: str = 'persons'
    es_genres_index: str = 'genres'

    redis_host: str = '127.0.0.1'
    redis_port: int = 6379

    elastic_host: str = '127.0.0.1'
    elastic_port: int = 9200
    elastic_schema: str = 'http://'

    base_dir: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


settings = Settings()
