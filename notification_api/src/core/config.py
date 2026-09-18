"""Конфигурация notification_api из переменных окружения."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Настройки приложения. Префикс NOTIFICATIONS_ — .env общий на весь
    проект, без префикса перехватывал бы переменные других сервисов."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Notification API", alias="NOTIFICATIONS_APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")

    # PostgreSQL — лог заявок, отправленных в Kafka (docs/
    # notification_requests_contract.md §9). Своя БД, отдельная от auth_service.
    # Без "S" — так называется реально заданная переменная (.env.example,
    # сервис notification_postgres в docker-compose.yml); с "S" такой
    # переменной никогда не было, и подключение всегда уходило на дефолтный
    # localhost, то есть notification_log не писался ни в одном окружении.
    postgres_host: str = Field(
        default="notification_postgres", alias="NOTIFICATION_POSTGRES_HOST"
    )
    postgres_port: int = Field(default=5432, alias="NOTIFICATION_POSTGRES_PORT")
    postgres_db: str = Field(
        default="notifications_db", alias="NOTIFICATION_POSTGRES_DB"
    )
    postgres_user: str = Field(
        default="notify_user", alias="NOTIFICATION_POSTGRES_USER"
    )
    postgres_password: str = Field(
        default="notify_secret", alias="NOTIFICATION_POSTGRES_PASSWORD"
    )

    # Kafka
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", alias="NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS"
    )
    kafka_topic_requests: str = Field(
        default="notifications.requests.v1",
        alias="NOTIFICATIONS_KAFKA_TOPIC_REQUESTS",
    )
    # Ждать подтверждения от всех ISR-реплик перед ack клиенту (по аналогии с
    # event_api — durability принятых заявок).
    kafka_acks: str = Field(default="all", alias="NOTIFICATIONS_KAFKA_ACKS")

    # Авторизация вызывающих сервисов. Пустая строка — проверка выключена
    # (локальная разработка). Один общий ключ на все источники (docs/
    # notification_requests_contract.md §2) — per-service ключи можно
    # добавить позже без изменения схемы.
    api_key: str = Field(default="", alias="NOTIFICATIONS_API_KEY")

    # Пакетная отправка (POST /api/v1/notifications/batch)
    batch_max_size: int = Field(default=100, alias="NOTIFICATIONS_BATCH_MAX_SIZE")

    # Максимум получателей в одной заявке (контракт §3) — ограничивает фан-аут
    # одного HTTP-запроса в Kafka-сообщения.
    max_recipients: int = Field(default=1000, alias="NOTIFICATIONS_MAX_RECIPIENTS")

    # Rate limiting. Как и у event_api, лимитер in-memory — per-instance, а не
    # общий на все реплики при горизонтальном масштабировании.
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_notifications: str = Field(
        default="200/minute", alias="NOTIFICATIONS_RATE_LIMIT_NOTIFICATIONS"
    )
    rate_limit_default: str = Field(
        default="300/minute", alias="NOTIFICATIONS_RATE_LIMIT_DEFAULT"
    )

    log_level: str = Field(default="INFO", alias="NOTIFICATIONS_LOG_LEVEL")

    # auth_service (S10_T4, issue #97): проверка токена websocket-клиента.
    # Без префикса NOTIFICATIONS_ — общая для всего проекта переменная (тот
    # же AUTH_SERVICE_URL, что у async_api/ugc_service).
    auth_service_url: str = Field(
        default="http://auth_service:8000/api/v1/auth", alias="AUTH_SERVICE_URL"
    )
    auth_service_timeout: float = Field(default=3.0, alias="AUTH_SERVICE_TIMEOUT")

    jaeger_endpoint: str = Field(default="", alias="JAEGER_ENDPOINT")

    # Пусто = Sentry отключён (DSN создаётся в проекте на sentry.io)
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    @property
    def postgres_dsn(self) -> str:
        """Async DSN для SQLAlchemy/приложения."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
