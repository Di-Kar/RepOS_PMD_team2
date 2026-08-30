"""Модель закладок."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from pydantic import Field


class Bookmark(Document):
    """Закладка пользователя на фильм."""

    user_id: UUID
    film_id: UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = 'bookmarks'
        indexes = [
            'user_id',
            'film_id',
            [('user_id', 1), ('film_id', 1)],  # уникальный индекс
        ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
