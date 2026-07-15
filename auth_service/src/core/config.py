"""Application configuration."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Все переменные с префиксом AUTH_: .env общий на весь проект,
    # и без префикса auth перехватывал бы POSTGRES_*/SECRET_KEY других сервисов.
    app_name: str = Field(default="Auth Service", alias="AUTH_APP_NAME")
    debug: bool = Field(default=False, alias="AUTH_DEBUG")

    # PostgreSQL Configuration
    postgres_host: str = Field(default="localhost", alias="AUTH_POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="AUTH_POSTGRES_PORT")
    postgres_db: str = Field(default="auth_db", alias="AUTH_POSTGRES_DB")
    postgres_user: str = Field(default="auth_user", alias="AUTH_POSTGRES_USER")
    postgres_password: str = Field(default="auth_password", alias="AUTH_POSTGRES_PASSWORD")

    # Redis Configuration
    redis_host: str = Field(default="localhost", alias="AUTH_REDIS_HOST")
    redis_port: int = Field(default=6379, alias="AUTH_REDIS_PORT")
    redis_db: int = Field(default=0, alias="AUTH_REDIS_DB")
    redis_password: str = Field(default="", alias="AUTH_REDIS_PASSWORD")

    # Logging
    log_level: str = Field(default="INFO", alias="AUTH_LOG_LEVEL")

    # JWT
    # Дефолт нужен, чтобы миграции/тесты работали без .env; в бою ключ задаётся через AUTH_SECRET_KEY.
    secret_key: str = Field(default="insecure-dev-secret-key-change-me-32ch", alias="AUTH_SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="AUTH_JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="AUTH_ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="AUTH_REFRESH_TOKEN_EXPIRE_DAYS")

    @property
    def postgres_dsn(self) -> str:
        """Construct async PostgreSQL database DSN."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """Construct sync PostgreSQL database DSN for Alembic."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_dsn(self) -> str:
        """Construct Redis DSN."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
# Global settings instance
settings = get_settings()
