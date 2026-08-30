"""Модель лайков."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from pydantic import Field


class Like(Document):
    """Лайк пользователя к фильму (оценка от 0 до 10)."""

    user_id: UUID
    film_id: UUID
    rating: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = 'likes'
        indexes = [
            'user_id',
            'film_id',
            [('user_id', 1), ('film_id', 1)],  # уникальный индекс
        ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
