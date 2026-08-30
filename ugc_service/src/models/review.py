"""Модели рецензий и голосований."""

from datetime import datetime
from uuid import UUID

from beanie import Document
from bson import ObjectId
from pydantic import Field


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

    user_id: UUID
    review_id: ObjectId
    is_like: bool
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = 'review_votes'
        indexes = [
            'user_id',
            'review_id',
            [('user_id', 1), ('review_id', 1)],  # уникальный индекс
        ]

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
