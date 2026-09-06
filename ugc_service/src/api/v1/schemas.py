"""Pydantic-схемы для API рецензий."""

from uuid import UUID

from pydantic import BaseModel, Field


class ReviewCreateRequest(BaseModel):
    """Запрос на создание рецензии (request body)."""

    film_id: UUID = Field(
        ...,
        description='UUID фильма',
        examples=['550e8400-e29b-41d4-a716-446655440000'],
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        examples=['Отличный фильм'],
        description='Заголовок рецензии',
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        examples=['Прекрасная история с глубокими персонажами и отличным сюжетом.'],
        description='Текст рецензии',
    )
    rating: int = Field(
        ...,
        ge=0,
        le=10,
        examples=[9],
        description='Оценка от 0 до 10',
    )


class ReviewUpdateRequest(BaseModel):
    """Запрос на обновление рецензии (request body)."""

    title: str | None = Field(
        None,
        min_length=1,
        max_length=200,
        examples=['Отличный фильм (обновлено)'],
        description='Новый заголовок рецензии',
    )
    text: str | None = Field(
        None,
        min_length=1,
        max_length=10000,
        examples=['Обновлённый текст рецензии.'],
        description='Новый текст рецензии',
    )
    rating: int | None = Field(
        None,
        ge=0,
        le=10,
        examples=[10],
        description='Новая оценка от 0 до 10',
    )
