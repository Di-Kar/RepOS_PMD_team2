"""Сервис работы с закладками."""

import logging
from uuid import UUID

from models.bookmark import Bookmark

logger = logging.getLogger(__name__)


async def add_bookmark(user_id: UUID, film_id: UUID) -> Bookmark:
    """Добавить фильм в закладки пользователя."""
    # Проверяем, нет ли уже такой закладки
    existing = await Bookmark.find_one(
        Bookmark.user_id == user_id,
        Bookmark.film_id == film_id,
    )
    if existing:
        return existing

    bookmark = Bookmark(user_id=user_id, film_id=film_id)
    await bookmark.insert()
    logger.info('Закладка создана: user=%s film=%s', user_id, film_id)
    return bookmark


async def remove_bookmark(user_id: UUID, film_id: UUID) -> bool:
    """Удалить фильм из закладок пользователя."""
    bookmark = await Bookmark.find_one(
        Bookmark.user_id == user_id,
        Bookmark.film_id == film_id,
    )
    if bookmark:
        await bookmark.delete()
        logger.info('Закладка удалена: user=%s film=%s', user_id, film_id)
        return True
    return False


async def get_user_bookmarks(
    user_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[Bookmark]:
    """Получить список закладок пользователя."""
    bookmarks = await Bookmark.find(
        Bookmark.user_id == user_id,
        skip=skip,
        limit=limit,
    ).to_list()
    return bookmarks


async def get_bookmark_by_film(user_id: UUID, film_id: UUID) -> Bookmark | None:
    """Проверить, есть ли фильм в закладках."""
    return await Bookmark.find_one(
        Bookmark.user_id == user_id,
        Bookmark.film_id == film_id,
    )
