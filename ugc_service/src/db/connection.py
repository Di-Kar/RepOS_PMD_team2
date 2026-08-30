"""Подключение к MongoDB через Beanie."""

import logging

from beanie import init_beanie
from config import settings
from models.bookmark import Bookmark
from models.like import Like
from models.review import Review, ReviewVote
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


async def get_client() -> AsyncIOMotorClient:
    """Получить клиент MongoDB (ленивая инициализация)."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
        logger.info('Подключено к MongoDB: %s', settings.mongo_uri)
    return _client


async def init_db():
    """Инициализировать Beanie с моделями."""
    client = await get_client()
    await init_beanie(
        database=client[settings.mongo_db],
        document_models=[Bookmark, Like, Review, ReviewVote],
    )
    logger.info('Beanie инициализирован, база: %s', settings.mongo_db)


async def close_db():
    """Закрыть соединение с MongoDB."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info('Соединение с MongoDB закрыто')
