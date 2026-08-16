"""Конфигурация event_api из переменных окружения."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Настройки приложения. Префикс EVENTS_ — .env общий на весь проект,
    без префикса перехватывал бы переменные других сервисов."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Event API", alias="EVENTS_APP_NAME")
    debug: bool = Field(default=False, alias="EVENTS_DEBUG")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="EVENTS_KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_clicks: str = Field(default="analytics.clicks.v1", alias="EVENTS_KAFKA_TOPIC_CLICKS")
    kafka_topic_pageviews: str = Field(default="analytics.pageviews.v1", alias="EVENTS_KAFKA_TOPIC_PAGEVIEWS")
    kafka_topic_custom_events: str = Field(
        default="analytics.custom_events.v1", alias="EVENTS_KAFKA_TOPIC_CUSTOM_EVENTS"
    )
    # Ждать подтверждения от всех ISR-реплик перед ack клиенту (NFR-7: durability).
    kafka_acks: str = Field(default="all", alias="EVENTS_KAFKA_ACKS")

    # Авторизация клиентской части (NFR-20). Пустая строка — проверка выключена (локальная разработка).
    api_key: str = Field(default="", alias="EVENTS_API_KEY")

    # Пакетная отправка (NFR-5)
    batch_max_size: int = Field(default=100, alias="EVENTS_BATCH_MAX_SIZE")

    # Rate limiting (NFR-21). На диаграмме TO BE у event_api нет своего хранилища
    # (Redis и т.п.), поэтому лимитер работает in-memory — per-instance, а не
    # общий на все реплики при горизонтальном масштабировании (NFR-11).
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_events: str = Field(default="200/minute", alias="EVENTS_RATE_LIMIT_EVENTS")
    rate_limit_default: str = Field(default="300/minute", alias="EVENTS_RATE_LIMIT_DEFAULT")

    log_level: str = Field(default="INFO", alias="EVENTS_LOG_LEVEL")

    jaeger_endpoint: str = Field(default="", alias="JAEGER_ENDPOINT")


settings = Settings()
