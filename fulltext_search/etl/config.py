from pydantic import Field
from pydantic_settings import BaseSettings


class PostgresSettings(BaseSettings):
    host: str = Field(default='localhost', alias='POSTGRES_HOST')
    port: int = Field(default=5432, alias='POSTGRES_PORT')
    dbname: str = Field(alias='POSTGRES_DB')
    user: str = Field(alias='POSTGRES_USER')
    password: str = Field(alias='POSTGRES_PASSWORD')

    model_config = {'populate_by_name': True, 'env_file': '.env'}


class ElasticsearchSettings(BaseSettings):
    host: str = Field(default='localhost', alias='ES_HOST')
    port: int = Field(default=9200, alias='ES_PORT')
    movies_index_name: str = Field(default='movies', alias='ES_MOVIES_INDEX_NAME')
    genres_index_name: str = Field(default='genres', alias='ES_GENRES_INDEX_NAME')
    persons_index_name: str = Field(default='persons', alias='ES_PERSONS_INDEX_NAME')

    @property
    def url(self) -> str:
        return f'http://{self.host}:{self.port}'

    model_config = {'populate_by_name': True, 'env_file': '.env'}


class ETLSettings(BaseSettings):
    batch_size: int = Field(default=100, alias='ETL_BATCH_SIZE')
    sleep_interval: int = Field(default=60, alias='ETL_SLEEP_INTERVAL')
    state_file: str = Field(default='state.json', alias='ETL_STATE_FILE')
    backoff_max_attempts: int = Field(default=0, alias='ETL_BACKOFF_MAX_ATTEMPTS')
    backoff_start_sleep_time: float = Field(
        default=0.1, alias='ETL_BACKOFF_START_SLEEP_TIME'
    )
    backoff_border_sleep_time: float = Field(
        default=10.0, alias='ETL_BACKOFF_BORDER_SLEEP_TIME'
    )

    model_config = {'populate_by_name': True, 'env_file': '.env'}


postgres_settings = PostgresSettings()
es_settings = ElasticsearchSettings()
etl_settings = ETLSettings()
