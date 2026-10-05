"""Конфигурация сервиса ugc_service."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    project_name: str = Field(default='ugc_service', alias='PROJECT_NAME')

    @field_validator('project_name', mode='before')
    @classmethod
    def ensure_project_name(cls, v: str | None) -> str:
        """Гарантируем, что project_name никогда не будет пустым."""
        return v or 'ugc_service'


    # ==================================================================== #
    #  MongoDB                                                              #
    # ==================================================================== #
    mongo_uri: str = Field(
        default='mongodb://ugc_service:ugc_service_secret_pass_2024@mongo_mongos-0:27017,mongo_mongos-1:27017/ugc_service?authSource=admin',
        alias='MONGO_URI',
    )
    mongo_db: str = Field(default='ugc_service', alias='MONGO_DB')

    # ==================================================================== #
    #  Auth Service                                                         #
    # ==================================================================== #
    auth_service_url: str = Field(
        default='http://auth_service:8000/api/v1/auth',
        alias='AUTH_SERVICE_URL',
    )
    auth_request_timeout: float = Field(
        default=1.5,
        alias='AUTH_REQUEST_TIMEOUT',
    )

    # ==================================================================== #
    #  Redis (кэш статистики + rate limiter)                                #
    # ==================================================================== #
    redis_host: str = Field(default='ugc_redis', alias='REDIS_HOST')
    redis_port: int = Field(default=6379, alias='REDIS_PORT')
    
    redis_db_cache: int = Field(
        default=0,
        alias='REDIS_DB_CACHE',
        description='DB Redis для кэша статистики фильмов (get_film_like_stats)',
    )
    film_stats_cache_ttl: int = Field(
        default=60,
        alias='FILM_STATS_CACHE_TTL',
        description='TTL кэша статистики фильма в секундах',
    )
    
    # Rate Limiter (защита от спама рецензиями)
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

    # ==================================================================== #
    #  S2S (Service-to-Service) авторизация                                 #
    # ==================================================================== #
    # Авторизация S2S-вызовов (user_profiles, GET /api/v1/internal/..., S11_T6)
    # — копия PROFILES_INTERNAL_API_KEY/AUTH_INTERNAL_API_KEY. Пусто = проверка
    # отключена (локальная разработка).
    internal_api_key: str = Field(default='', alias='UGC_INTERNAL_API_KEY')

    # ==================================================================== #
    #  Debug / Observability                                                #
    # ==================================================================== #
    debug: bool = Field(default=False, alias='DEBUG')

    # Пусто = Sentry отключён (DSN создаётся в проекте на sentry.io)
    sentry_dsn: str = Field(default='', alias='SENTRY_DSN')


settings = Settings()