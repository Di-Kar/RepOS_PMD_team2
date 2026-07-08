"""
PostgreSQL database connection module.
Provides async SQLAlchemy engine, session management and dependency injection.
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from src.core.config import settings

# Create async engine
engine = create_async_engine(
    settings.database_dsn,
    echo=settings.debug,  # Log SQL queries in debug mode
    pool_size=10,  # Maximum number of connections in the pool
    max_overflow=20,  # Maximum overflow connections beyond pool_size
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,  # Recycle connections after 1 hour
)

# Create async session maker
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)

# Alias for backward compatibility
async_session_maker = AsyncSessionLocal

# Create declarative base for models
Base = declarative_base()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function that provides database session.

    Yields:
        AsyncSession: Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database - create all tables.

    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
