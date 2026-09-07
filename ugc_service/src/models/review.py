"""Модели рецензий и голосований."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from bson import ObjectId
from pydantic import Field


def review_vote_id(user_id: UUID, review_id: ObjectId) -> str:
    """Детерминированный _id голоса из пары идентификаторов.

    Уникальность пары (user_id, review_id) гарантируется первичным ключом _id —
    он всегда уникален, в том числе в шардированной коллекции с любым shard key.
    """
    return f'{user_id}:{review_id}'


class Review(Document):
    """Рецензия пользователя на фильм."""

    user_id: UUID
    film_id: UUID
    title: str
    text: str
    rating: int
    published_at: datetime = Field(default_factory=datetime.utcnow)
    likes_count: int = 0
    dislikes_count: int = 0

    class Settings:
        name = 'reviews'
        indexes = [
            'user_id',
            'film_id',
            'published_at',
            'rating',
            [('film_id', 1), ('likes_count', -1)],  # сортировка по полезности
        ]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class ReviewVote(Document):
    """Голос за/против рецензии."""

    id: str
    user_id: UUID
    review_id: ObjectId
    is_like: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = 'review_votes'
        indexes = [
            'user_id',
            'review_id',
        ]

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
