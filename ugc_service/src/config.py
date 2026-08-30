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
        default='mongodb://mongo_mongos-0:27017,mongo_mongos-1:27018',
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

    # Debug
    debug: bool = Field(default=False, alias='DEBUG')


settings = Settings()
