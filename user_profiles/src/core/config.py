"""Конфигурация user_profiles из переменных окружения.

Скелет сервиса (S11_T2, issue #109) — CRUD-бизнес-логика добавится в S11_T3
(docs/user_profiles_contract.md). AUTH_SERVICE_URL/AUTH_SERVICE_TIMEOUT/
AUTH_INTERNAL_API_KEY — БЕЗ префикса PROFILES_: те же глобальные переменные,
которыми уже пользуются link_shortener_service/notification_worker для
обращений к auth_service — заводить отдельную копию под тем же смыслом было
бы дублированием."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Префикс PROFILES_ — .env общий на весь проект, без префикса
    перехватывал бы переменные других сервисов."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="User Profiles Service", alias="PROFILES_APP_NAME")
    debug: bool = Field(default=False, alias="DEBUG")

    # PostgreSQL — своя БД, отдельная от остальных сервисов.
    postgres_host: str = Field(
        default="user_profiles_postgres", alias="PROFILES_POSTGRES_HOST"
    )
    postgres_port: int = Field(default=5432, alias="PROFILES_POSTGRES_PORT")
    postgres_db: str = Field(default="profiles_db", alias="PROFILES_POSTGRES_DB")
    postgres_user: str = Field(default="profiles_user", alias="PROFILES_POSTGRES_USER")
    postgres_password: str = Field(
        default="profiles_secret", alias="PROFILES_POSTGRES_PASSWORD"
    )

    # Авторизация входящих S2S-запросов от admin_panel (internal API,
    # docs/user_profiles_contract.md §2, см. src/api/v1/dependencies.py:
    # verify_internal_api_key). Пусто = проверка выключена (локальная
    # разработка) — по образцу AUTH_INTERNAL_API_KEY.
    internal_api_key: str = Field(default="", alias="PROFILES_INTERNAL_API_KEY")

    log_level: str = Field(default="INFO", alias="PROFILES_LOG_LEVEL")

    # auth_service (валидация JWT self-service эндпоинтов /api/v1/profiles/me
    # в S11_T3) — глобальные переменные, уже заданные для
    # link_shortener_service/notification_worker.
    auth_service_url: str = Field(
        default="http://auth_service:8000/api/v1/auth", alias="AUTH_SERVICE_URL"
    )
    auth_service_timeout: float = Field(default=3.0, alias="AUTH_SERVICE_TIMEOUT")
    auth_internal_api_key: str = Field(default="", alias="AUTH_INTERNAL_API_KEY")

    # ugc_service (агрегирующая витрина профиля, GET /profiles/{user_id}/full,
    # S11_T6) — internal-эндпоинт ugc_service, см.
    # ugc_service/src/api/v1/internal.py.
    ugc_service_url: str = Field(
        default="http://ugc_service:8000", alias="UGC_SERVICE_URL"
    )
    ugc_service_timeout: float = Field(default=2.0, alias="UGC_SERVICE_TIMEOUT")
    ugc_internal_api_key: str = Field(default="", alias="UGC_INTERNAL_API_KEY")

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
