"""Сервис работы с закладками."""

import logging
from uuid import UUID

from models.bookmark import Bookmark, bookmark_id
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)


async def add_bookmark(user_id: UUID, film_id: UUID, film_title: str) -> Bookmark:
    """Добавить фильм в закладки пользователя (идемпотентно)."""
    bookmark = Bookmark(
        id=bookmark_id(user_id, film_id),
        user_id=user_id,
        film_id=film_id,
        film_title=film_title,
    )
    try:
        await bookmark.insert()
    except DuplicateKeyError:
        # Гонка двух параллельных запросов: закладка уже создана — возвращаем её.
        return await Bookmark.get(bookmark_id(user_id, film_id))

    logger.info('Закладка создана: user=%s film=%s', user_id, film_id)
    return bookmark


async def remove_bookmark(user_id: UUID, film_id: UUID) -> bool:
    """Удалить фильм из закладок пользователя."""
    bookmark = await Bookmark.get(bookmark_id(user_id, film_id))
    if bookmark:
        await bookmark.delete()
        logger.info('Закладка удалена: user=%s film=%s', user_id, film_id)
        return True
    return False


_SORT_MAP = {
    'added_at': [('created_at', -1)],
    'title': [('film_title', 1)],
}


async def get_user_bookmarks(
    user_id: UUID,
    sort_by: str = 'added_at',
    skip: int = 0,
    limit: int = 50,
) -> list[Bookmark]:
    """Получить список закладок пользователя с сортировкой (S11_T13)."""
    sort_field = _SORT_MAP.get(sort_by, _SORT_MAP['added_at'])
    bookmarks = (
        await Bookmark.find(Bookmark.user_id == user_id)
        .sort(*sort_field)
        .skip(skip)
        .limit(limit)
        .to_list()
    )
    return bookmarks


async def get_bookmark_by_film(user_id: UUID, film_id: UUID) -> Bookmark | None:
    """Проверить, есть ли фильм в закладках."""
    return await Bookmark.get(bookmark_id(user_id, film_id))
