"""Общие Pydantic response-модели для ugc_service.

Используются ugc_service для сериализации ответов и async_api для
приёма данных от ugc_service (по аналогии с shared/event_schemas.py).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

EXAMPLE_FILM_ID = UUID('550e8400-e29b-41d4-a716-446655440000')
EXAMPLE_USER_ID = UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
EXAMPLE_REVIEW_ID = UUID('770e8400-e29b-41d4-a716-446655440000')

# ==================================================================== #
#  Закладки                                                              #
# ==================================================================== #


class BookmarkSchema(BaseModel):
    """Закладка пользователя на фильм."""

    film_id: UUID = Field(
        EXAMPLE_FILM_ID,
        description='UUID фильма',
        examples=['550e8400-e29b-41d4-a716-446655440000'],
    )
    film_title: str = Field(
        'Интерстеллар',
        description='Название фильма',
        examples=['Интерстеллар'],
    )
    film_poster: str | None = Field(
        None,
        description='URL постера фильма',
        examples=['https://example.com/poster.jpg'],
    )
    added_at: datetime = Field(
        datetime(2026, 8, 30, 10, 0, 0),
        description='Дата добавления в закладки',
        examples=['2026-08-30T10:00:00'],
    )


# ==================================================================== #
#  Лайки                                                                 #
# ==================================================================== #


class LikeSchema(BaseModel):
    """Лайк пользователя к фильму."""

    user_id: UUID = Field(
        EXAMPLE_USER_ID,
        description='UUID пользователя',
        examples=['6ba7b810-9dad-11d1-80b4-00c04fd430c8'],
    )
    film_id: UUID = Field(
        EXAMPLE_FILM_ID,
        description='UUID фильма',
        examples=['550e8400-e29b-41d4-a716-446655440000'],
    )
    rating: int = Field(
        8,
        ge=0,
        le=10,
        description='Оценка от 0 (дизлайк) до 10 (лайк)',
        examples=[8],
    )
    created_at: datetime = Field(
        datetime(2026, 8, 30, 10, 0, 0),
        description='Дата добавления лайка',
        examples=['2026-08-30T10:00:00'],
    )


class LikeStatsSchema(BaseModel):
    """Статистика лайков для фильма."""

    film_id: UUID = Field(
        EXAMPLE_FILM_ID,
        description='UUID фильма',
        examples=['550e8400-e29b-41d4-a716-446655440000'],
    )
    total_likes: int = Field(
        0,
        description='Количество лайков (rating > 5)',
        examples=[150],
    )
    total_dislikes: int = Field(
        0,
        description='Количество дизлайков (rating < 3)',
        examples=[30],
    )
    average_rating: float = Field(
        0.0,
        description='Средняя оценка',
        examples=[7.5],
    )
    total_ratings: int = Field(
        0,
        description='Всего оценок',
        examples=[180],
    )
    rating_distribution: dict = Field(
        default_factory=dict,
        description='Распределение оценок {0: N, 1: N, ..., 10: N}',
        examples=[
            {0: 5, 1: 3, 2: 8, 3: 14, 4: 20, 5: 25, 6: 20, 7: 25, 8: 22, 9: 15, 10: 23}
        ],
    )


# ==================================================================== #
#  Голосование за рецензии                                               #
# ==================================================================== #


class ReviewVoteSchema(BaseModel):
    """Голос за/против рецензии."""

    review_id: UUID = Field(
        EXAMPLE_REVIEW_ID,
        description='UUID рецензии',
        examples=['770e8400-e29b-41d4-a716-446655440000'],
    )
    is_like: bool = Field(
        True,
        description='True = лайк, False = дизлайк',
        examples=[True],
    )
    voted_at: datetime = Field(
        datetime(2026, 8, 30, 12, 0, 0),
        description='Дата голосования',
        examples=['2026-08-30T12:00:00'],
    )


# ==================================================================== #
#  Рецензии                                                              #
# ==================================================================== #


class ReviewSchema(BaseModel):
    """Рецензия пользователя на фильм."""

    id: UUID = Field(
        EXAMPLE_REVIEW_ID,
        description='UUID рецензии',
        examples=['770e8400-e29b-41d4-a716-446655440000'],
    )
    user_id: UUID = Field(
        EXAMPLE_USER_ID,
        description='UUID автора рецензии',
        examples=['6ba7b810-9dad-11d1-80b4-00c04fd430c8'],
    )
    user_name: str = Field(
        'Иван Петров',
        description='Имя автора',
        examples=['Иван Петров'],
    )
    film_id: UUID = Field(
        EXAMPLE_FILM_ID,
        description='UUID фильма',
        examples=['550e8400-e29b-41d4-a716-446655440000'],
    )
    title: str = Field(
        'Шедевр кино',
        description='Заголовок рецензии',
        examples=['Шедевр кино'],
    )
    text: str = Field(
        'Прекрасная история с глубокими персонажами и отличным сюжетом.',
        description='Текст рецензии',
        examples=['Прекрасная история с глубокими персонажами и отличным сюжетом.'],
    )
    rating: int = Field(
        9,
        ge=0,
        le=10,
        description='Оценка от 0 до 10',
        examples=[9],
    )
    published_at: datetime = Field(
        datetime(2026, 8, 30, 10, 0, 0),
        description='Дата публикации',
        examples=['2026-08-30T10:00:00'],
    )
    likes_count: int = Field(
        15,
        description='Количество лайков',
        examples=[15],
    )
    dislikes_count: int = Field(
        2,
        description='Количество дизлайков',
        examples=[2],
    )


class ReviewWithAuthorSchema(ReviewSchema):
    """Рецензия с дополнительными данными автора (для карточки фильма)."""

    author_avatar: str | None = Field(
        None,
        description='URL аватара автора',
        examples=['https://example.com/avatar.jpg'],
    )
