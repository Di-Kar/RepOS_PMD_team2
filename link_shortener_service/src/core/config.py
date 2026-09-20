"""Конфигурация link_shortener_service из переменных окружения.

Универсальный сократитель ссылок (docs/link_shortener_contract.md): принимает
S2S-заявку на создание короткой ссылки (POST /api/v1/links) и резолвит её по
клику (GET /r/{code}). Первый и пока единственный потребитель — auth_service
(ссылка подтверждения email в welcome-письме, purpose=email_confirmation),
но сервис не завязан на эту бизнес-логику намертво — purpose оставлен
расширяемым под будущие сценарии (сокращение любых ссылок в уведомлениях)."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Префикс LINKS_ — .env общий на весь проект, без префикса перехватывал
    бы переменные других сервисов. AUTH_SERVICE_URL/AUTH_INTERNAL_API_KEY —
    БЕЗ префикса LINKS_: те же глобальные переменные, которыми уже пользуются
    notification_api/notification_worker для обращений к auth_service —
    заводить отдельную копию под тем же смыслом было бы дублированием."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Link Shortener Service", alias="LINKS_APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")

    # PostgreSQL — своя БД, отдельная от остальных сервисов.
    postgres_host: str = Field(
        default="link_shortener_postgres", alias="LINKS_POSTGRES_HOST"
    )
    postgres_port: int = Field(default=5432, alias="LINKS_POSTGRES_PORT")
    postgres_db: str = Field(default="links_db", alias="LINKS_POSTGRES_DB")
    postgres_user: str = Field(default="links_user", alias="LINKS_POSTGRES_USER")
    postgres_password: str = Field(
        default="links_secret", alias="LINKS_POSTGRES_PASSWORD"
    )

    # Авторизация S2S-создателей ссылок (POST /api/v1/links). Пусто = проверка
    # выключена (локальная разработка) — по образцу NOTIFICATIONS_API_KEY.
    api_key: str = Field(default="", alias="LINKS_API_KEY")

    # Базовый публичный URL для сборки short_url в ответе POST /api/v1/links,
    # напр. "http://localhost:8006" в dev. short_url = public_base_url + "/r/" + code.
    public_base_url: str = Field(
        default="http://localhost:8006", alias="LINKS_PUBLIC_BASE_URL"
    )

    code_length: int = Field(default=7, alias="LINKS_CODE_LENGTH")
    code_alphabet: str = Field(
        default=(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        ),
        alias="LINKS_CODE_ALPHABET",
    )
    code_generation_max_attempts: int = Field(
        default=5, alias="LINKS_CODE_GEN_MAX_ATTEMPTS"
    )

    default_ttl_seconds: int = Field(default=86400, alias="LINKS_DEFAULT_TTL_SECONDS")
    max_ttl_seconds: int = Field(
        default=30 * 86400, alias="LINKS_MAX_TTL_SECONDS"
    )

    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_create: str = Field(
        default="120/minute", alias="LINKS_RATE_LIMIT_CREATE"
    )
    rate_limit_redirect: str = Field(
        default="60/minute", alias="LINKS_RATE_LIMIT_REDIRECT"
    )
    rate_limit_default: str = Field(
        default="300/minute", alias="LINKS_RATE_LIMIT_DEFAULT"
    )

    log_level: str = Field(default="INFO", alias="LINKS_LOG_LEVEL")

    # auth_service (для purpose=email_confirmation) — глобальные переменные,
    # уже заданные для notification_worker/notification_api (websocket-
    # авторизация, обогащение профилем).
    auth_service_url: str = Field(
        default="http://auth_service:8000/api/v1/auth", alias="AUTH_SERVICE_URL"
    )
    auth_service_timeout: float = Field(default=3.0, alias="AUTH_SERVICE_TIMEOUT")
    auth_internal_api_key: str = Field(default="", alias="AUTH_INTERNAL_API_KEY")

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
