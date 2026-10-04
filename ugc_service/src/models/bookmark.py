"""Модель закладок."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from pydantic import Field


def bookmark_id(user_id: UUID, film_id: UUID) -> str:
    """Детерминированный _id закладки из пары идентификаторов.

    Уникальность пары (user_id, film_id) гарантируется первичным ключом _id —
    он всегда уникален, в том числе в шардированной коллекции с любым shard key.
    """
    return f'{user_id}:{film_id}'


class Bookmark(Document):
    """Закладка пользователя на фильм."""

    id: str
    user_id: UUID
    film_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = 'bookmarks'
        indexes = [
            'user_id',
            'film_id',
            # (user_id, created_at): без него get_user_bookmarks (S11_T6)
            # сортирует по created_at после поиска по user_id в памяти —
            # на большом количестве закладок у пользователя упирается в
            # лимит blocking sort (32MB) без возможности использовать индекс.
            [('user_id', 1), ('created_at', -1)],
        ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
