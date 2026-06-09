from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    # База данных
    pg_dsn: str = Field(alias="PG_DSN")
    pg_fetch_size: int = Field(default=100, alias="PG_FETCH_SIZE")
    
    # Elasticsearch
    es_dsn: str = Field(alias="ES_DSN")
    es_index_name: str = Field(default="movies", alias="ES_INDEX_NAME")
    es_bulk_size: int = Field(default=500, alias="ES_BULK_SIZE")
    
    # ETL настройки
    poll_interval_seconds: int = Field(default=60, alias="POLL_INTERVAL_SECONDS")
    max_retries: int = Field(default=5, alias="MAX_RETRIES")

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")