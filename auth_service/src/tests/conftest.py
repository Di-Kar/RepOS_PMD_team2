import asyncio
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from redis.asyncio import Redis

from src.core.config import settings
from src.core.security import hash_password
from src.db.postgres import Base, get_session
from src.db.redis_db import get_redis
from src.models.entity import User, Role
from src.services.token_service import TokenService


@pytest.fixture(scope="function")
def event_loop():
    """Создаём event loop для каждого теста"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Создаёт отдельную сессию БД для каждого теста.
    После теста откатывает все изменения (через транзакцию).
    """
    engine = create_async_engine(
        settings.postgres_dsn,
        echo=False,
    )
    
    async with engine.begin() as conn:
        # Создаём все таблицы (если их нет)
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_factory() as session:
        yield session
    
    # Очистка после теста
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def redis_client() -> AsyncGenerator[Redis, None]:
    """Создаёт Redis клиент для тестов и очищает БД после"""
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=15,  # Используем отдельную БД для тестов (15)
        decode_responses=True,
    )
    
    # Очищаем тестовую БД перед тестом
    await client.flushdb()
    
    yield client
    
    # Очищаем после теста
    await client.flushdb()
    await client.close()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Создаёт тестового пользователя"""
    user = User(
        id=uuid.uuid4(),
        login=f"test_user_{uuid.uuid4().hex[:8]}",
        password="hashed_password_123",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_role(db_session: AsyncSession) -> Role:
    """Создаёт тестовую роль"""
    role = Role(
        id=uuid.uuid4(),
        name=f"test_role_{uuid.uuid4().hex[:8]}",
        description="Test role description",
        permissions=["video:watch"],
    )
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)
    return role


@pytest_asyncio.fixture
async def sample_superuser(db_session: AsyncSession) -> User:
    """Создаёт тестового суперпользователя"""
    user = User(
        id=uuid.uuid4(),
        login=f"test_superuser_{uuid.uuid4().hex[:8]}",
        password="hashed_password_123",
        first_name="Super",
        last_name="User",
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(redis_client: Redis):
    """Фабрика заголовков Authorization: выпускает настоящий access-токен для пользователя."""

    async def _make(user: User) -> dict:
        access_token, _ = await TokenService(redis_client).create_token_pair(user, [])
        return {"Authorization": f"Bearer {access_token}"}

    return _make


@pytest_asyncio.fixture
async def registered_user(db_session) -> User:
    """Пользователь с настоящим bcrypt-хэшем пароля (для логина через API)."""
    user = User(
        id=uuid.uuid4(),
        login=f"user_{uuid.uuid4().hex[:8]}@example.com",
        password=hash_password("SecurePass123!"),
        first_name="John",
        last_name="Doe",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, redis_client: Redis
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент для роутов, с подменой БД/Redis-зависимостей на тестовые фикстуры."""
    from src.main import app

    async def _get_session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _get_redis_override() -> Redis:
        return redis_client

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[get_redis] = _get_redis_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
