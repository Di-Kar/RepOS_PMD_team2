from pydantic import Field
from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    bootstrap_servers: str = Field(
        default='kafka:9092',
        alias='ANALYTICS_KAFKA_BOOTSTRAP_SERVERS',
    )
    consumer_group: str = Field(
        default='analytics_etl',
        alias='ANALYTICS_KAFKA_CONSUMER_GROUP',
    )
    topics: str = Field(
        default='analytics.clicks.v1,analytics.pageviews.v1,analytics.custom_events.v1',
        alias='ANALYTICS_KAFKA_TOPICS',
    )

    @property
    def topics_list(self) -> list[str]:
        return [t.strip() for t in self.topics.split(',') if t.strip()]

    model_config = {'populate_by_name': True, 'env_file': '.env', 'extra': 'ignore'}


class ClickHouseSettings(BaseSettings):
    host: str = Field(default='clickhouse', alias='ANALYTICS_CLICKHOUSE_HOST')
    port: int = Field(default=8123, alias='ANALYTICS_CLICKHOUSE_PORT')
    database: str = Field(default='analytics', alias='ANALYTICS_CLICKHOUSE_DATABASE')
    user: str = Field(default='default', alias='ANALYTICS_CLICKHOUSE_USER')
    password: str = Field(default='', alias='ANALYTICS_CLICKHOUSE_PASSWORD')

    model_config = {'populate_by_name': True, 'env_file': '.env', 'extra': 'ignore'}


class ETLSettings(BaseSettings):
    batch_size: int = Field(default=1000, alias='ANALYTICS_ETL_BATCH_SIZE')
    flush_interval: int = Field(default=5, alias='ANALYTICS_ETL_FLUSH_INTERVAL')
    state_dir: str = Field(default='/app/state', alias='ANALYTICS_ETL_STATE_DIR')
    memory_warn_mb: int = Field(default=500, alias='ANALYTICS_ETL_MEMORY_WARN_MB')
    memory_critical_mb: int = Field(default=800, alias='ANALYTICS_ETL_MEMORY_CRITICAL_MB')
    backoff_start: float = Field(default=0.1, alias='ANALYTICS_ETL_BACKOFF_START')
    backoff_border: float = Field(default=10.0, alias='ANALYTICS_ETL_BACKOFF_BORDER')
    backoff_max: int = Field(default=3, alias='ANALYTICS_ETL_BACKOFF_MAX')

    model_config = {'populate_by_name': True, 'env_file': '.env', 'extra': 'ignore'}


kafka_settings = KafkaSettings()
clickhouse_settings = ClickHouseSettings()
etl_settings = ETLSettings()
