"""Конфигурация сервиса ugc_service."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )

    project_name: str = 'ugc_service'

    # MongoDB
    mongo_uri: str = Field(
        default='mongodb://ugc_service:ugc_service_secret_pass_2024@mongo_mongos-0:27017,mongo_mongos-1:27017/ugc_service?authSource=admin',
        alias='MONGO_URI',
    )
    mongo_db: str = Field(default='ugc_service', alias='MONGO_DB')

    # Auth Service
    auth_service_url: str = Field(
        default='http://auth_service:8000/api/v1/auth',
        alias='AUTH_SERVICE_URL',
    )
    auth_request_timeout: float = Field(
        default=1.5,
        alias='AUTH_REQUEST_TIMEOUT',
    )

    # Rate Limiting (защита от спама рецензиями)
    reviews_rate_limit: str = Field(
        default='10/hour',
        alias='REVIEWS_RATE_LIMIT',
        description='Лимит на создание рецензий (формат slowapi: count/period)',
    )
    rate_limiter_storage_uri: str = Field(
        default='redis://ugc_redis:6379/1',
        alias='RATE_LIMITER_STORAGE_URI',
        description='URI Redis для хранения счетчиков rate limiter (отдельный DB=1)',
    )

    # Redis (кэш статистики фильмов)
    redis_host: str = Field(default='ugc_redis', alias='REDIS_HOST')
    redis_port: int = Field(default=6379, alias='REDIS_PORT')
    redis_db_cache: int = Field(
        default=0,
        alias='REDIS_DB_CACHE',
        description='DB Redis для кэша статистики фильмов',
    )
    film_stats_cache_ttl: int = Field(
        default=60,
        alias='FILM_STATS_CACHE_TTL',
        description='TTL кэша статистики фильма в секундах',
    )

    # Debug
    debug: bool = Field(default=False, alias='DEBUG')

    # Пусто = Sentry отключён (DSN создаётся в проекте на sentry.io)
    sentry_dsn: str = Field(default='', alias='SENTRY_DSN')


settings = Settings()