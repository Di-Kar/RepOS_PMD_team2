"""Асинхронное подключение к Postgres notification_api (лог отправленных в
Kafka заявок, docs/notification_requests_contract.md §9). Сессия открывается
напрямую в сервисном слое (src/services/notification_service.py), не через
FastAPI Depends — в этом сервисе к БД обращается только он, отдельного
HTTP-эндпоинта для чтения лога пока нет."""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from src.core.config import settings

engine = create_async_engine(
    settings.postgres_dsn,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def close_db() -> None:
    await engine.dispose()
