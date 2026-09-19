"""Конфигурация notification_worker из переменных окружения (docs/
notification_requests_contract.md). Обслуживает оба процесса (render и
email_sender) одной моделью настроек — по образцу
notification_api/src/core/config.py."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Настройки приложения. Префикс NOTIFICATION_WORKER_ — .env общий на
    весь проект, без префикса перехватывал бы переменные других сервисов."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(
        default="Notification Worker", alias="NOTIFICATION_WORKER_APP_NAME"
    )
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="NOTIFICATION_WORKER_LOG_LEVEL")

    # PostgreSQL — та же физическая БД notifications_db, что у
    # notification_api (notification_log) и notification_admin_panel
    # (message_templates/notifications/notification_contents/
    # notification_history) — разные таблицы, общий инстанс.
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
    postgres_pool_min_size: int = Field(
        default=2, alias="NOTIFICATION_WORKER_POSTGRES_POOL_MIN_SIZE"
    )
    postgres_pool_max_size: int = Field(
        default=10, alias="NOTIFICATION_WORKER_POSTGRES_POOL_MAX_SIZE"
    )

    # Kafka
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", alias="NOTIFICATION_WORKER_KAFKA_BOOTSTRAP_SERVERS"
    )
    kafka_topic_requests: str = Field(
        default="notifications.requests.v1",
        alias="NOTIFICATION_WORKER_KAFKA_TOPIC_REQUESTS",
    )
    kafka_topic_ready: str = Field(
        default="notifications.ready.v1",
        alias="NOTIFICATION_WORKER_KAFKA_TOPIC_READY",
    )
    kafka_consumer_group_render: str = Field(
        default="notification_worker_render",
        alias="NOTIFICATION_WORKER_KAFKA_CONSUMER_GROUP_RENDER",
    )
    kafka_consumer_group_send: str = Field(
        default="notification_worker_email_sender",
        alias="NOTIFICATION_WORKER_KAFKA_CONSUMER_GROUP_SEND",
    )
    # Идемпотентный продюсер для notifications.ready.v1 — тот же приём, что
    # у notification_api для notifications.requests.v1.
    kafka_acks: str = Field(default="all", alias="NOTIFICATION_WORKER_KAFKA_ACKS")

    # Ретраи транзиентных ошибок (auth_service/SMTP недоступны) внутри
    # обработки одного сообщения — до того, как поставить консьюмер на паузу
    # по этой партиции (§5.3 плана).
    retry_max_attempts: int = Field(
        default=3, alias="NOTIFICATION_WORKER_RETRY_MAX_ATTEMPTS"
    )
    retry_backoff_seconds: float = Field(
        default=2.0, alias="NOTIFICATION_WORKER_RETRY_BACKOFF_SECONDS"
    )
    partition_pause_seconds: float = Field(
        default=30.0, alias="NOTIFICATION_WORKER_PARTITION_PAUSE_SECONDS"
    )

    # Send-стадия: сколько секунд статус notifications.status='sending'
    # считается "живым" (тот же процесс всё ещё ретраит отправку) прежде
    # чем считаться зависшим после падения процесса (см.
    # send_service._claim_for_sending). Не настоящая распределённая
    # блокировка с owner-id — эвристика по времени, достаточная при
    # гарантии Kafka "одна партиция — один консьюмер группы одновременно";
    # окно должно быть заметно больше, чем реалистичное время одной серии
    # ретраев (retry_max_attempts * smtp_timeout).
    send_lease_seconds: float = Field(
        default=120.0, alias="NOTIFICATION_WORKER_SEND_LEASE_SECONDS"
    )

    # TTL кэша message_templates в памяти — шаблоны меняются редко
    # (управляются вручную через notification_admin_panel), а читаются на
    # каждое уведомление.
    template_cache_ttl_seconds: float = Field(
        default=60.0, alias="NOTIFICATION_WORKER_TEMPLATE_CACHE_TTL_SECONDS"
    )

    # auth_service — internal-эндпоинт профиля по user_id (S10_T3, issue #96)
    auth_service_url: str = Field(
        default="http://auth_service:8000/api/v1/auth", alias="AUTH_SERVICE_URL"
    )
    auth_service_timeout: float = Field(default=3.0, alias="AUTH_SERVICE_TIMEOUT")
    auth_internal_api_key: str = Field(default="", alias="AUTH_INTERNAL_API_KEY")

    # SMTP (email_sender)
    smtp_host: str = Field(default="mailhog", alias="NOTIFICATION_WORKER_SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="NOTIFICATION_WORKER_SMTP_PORT")
    smtp_user: str = Field(default="", alias="NOTIFICATION_WORKER_SMTP_USER")
    smtp_password: str = Field(default="", alias="NOTIFICATION_WORKER_SMTP_PASSWORD")
    smtp_from_email: str = Field(
        default="noreply@repospmd.local", alias="NOTIFICATION_WORKER_SMTP_FROM_EMAIL"
    )
    smtp_use_tls: bool = Field(
        default=False, alias="NOTIFICATION_WORKER_SMTP_USE_TLS"
    )
    smtp_timeout: float = Field(default=10.0, alias="NOTIFICATION_WORKER_SMTP_TIMEOUT")
    # Пул переиспользуемых SMTP-соединений (src/clients/email_client.py) —
    # без него каждое письмо открывало и закрывало бы новое TCP/SMTP-
    # соединение. Дефолт 3 — по числу партиций топика (kafka_init создаёт 3),
    # чтобы при полной параллельной нагрузке ни одна partition-задача
    # send-стадии не ждала свободное соединение.
    smtp_pool_size: int = Field(default=3, alias="NOTIFICATION_WORKER_SMTP_POOL_SIZE")

    jaeger_endpoint: str = Field(default="", alias="JAEGER_ENDPOINT")

    # Пусто = Sentry отключён (DSN создаётся в проекте на sentry.io)
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    @property
    def postgres_dsn(self) -> str:
        """DSN для asyncpg (не SQLAlchemy — воркер пишет в чужие таблицы
        (Django-схема notification_admin_panel) сырым SQL, без ORM)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
