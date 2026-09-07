"""Модель лайков."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from pydantic import Field


def like_id(user_id: UUID, film_id: UUID) -> str:
    """Детерминированный _id оценки из пары идентификаторов.

    Уникальность пары (user_id, film_id) гарантируется первичным ключом _id —
    он всегда уникален, в том числе в шардированной коллекции с любым shard key.
    """
    return f'{user_id}:{film_id}'


class Like(Document):
    """Лайк пользователя к фильму (оценка от 0 до 10)."""

    id: str
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
        ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
