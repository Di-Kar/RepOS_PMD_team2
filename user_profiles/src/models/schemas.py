"""Pydantic-схемы HTTP API user_profiles (docs/user_profiles_contract.md §1-2)."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# E.164: '+' и от 2 до 15 цифр, первая цифра после '+' не ноль.
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


class ProfileWriteRequest(BaseModel):
    """Общие поля создания/обновления профиля — полная замена, не patch."""

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["Иван"],
        description="Имя",
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["Иванов"],
        description="Фамилия",
    )
    phone: str = Field(
        ...,
        examples=["+79991234567"],
        description="Телефон в формате E.164, уникален по всем профилям",
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not _E164_PATTERN.fullmatch(value):
            raise ValueError("Phone must be in E.164 format, e.g. +79991234567")
        return value


class ProfileCreateRequest(ProfileWriteRequest):
    """Запрос на создание своего профиля (request body)."""


class ProfileUpdateRequest(ProfileWriteRequest):
    """Запрос на обновление ФИО/телефона (request body)."""


class ProfileResponse(BaseModel):
    """Профиль пользователя (response body)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID = Field(
        ...,
        description="Совпадает с id пользователя в auth_service",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    first_name: str = Field(..., description="Имя")
    last_name: str = Field(..., description="Фамилия")
    phone: str = Field(..., description="Телефон в формате E.164")
    created_at: datetime = Field(..., description="Дата создания профиля")
    updated_at: datetime = Field(..., description="Дата последнего обновления")


class ProfileListResponse(BaseModel):
    """Страница результатов поиска/листинга профилей (internal API)."""

    items: list[ProfileResponse] = Field(..., description="Профили на странице")
    total: int = Field(..., description="Общее количество совпадений")


class UgcBookmarkItem(BaseModel):
    """Закладка пользователя (зеркалит BookmarkResponse ugc_service)."""

    film_id: uuid.UUID
    added_at: str


class UgcRatingItem(BaseModel):
    """Оценка, выставленная пользователем фильму (зеркалит LikeResponse
    ugc_service)."""

    film_id: uuid.UUID
    rating: int
    updated_at: str


class UgcReviewItem(BaseModel):
    """Рецензия пользователя (зеркалит ReviewResponse ugc_service)."""

    id: str
    film_id: uuid.UUID
    title: str
    rating: int
    published_at: str
    likes_count: int
    dislikes_count: int


class ProfileFullResponse(BaseModel):
    """Агрегирующая витрина профиля (docs/user_profiles_contract.md §2,
    GET /api/v1/profiles/{user_id}/full)."""

    profile: ProfileResponse
    ugc_available: bool = Field(
        ...,
        description="False — ugc_service был недоступен при сборке ответа, "
        "списки ниже пустые, а не отсутствующие UGC-данные",
    )
    bookmarks: list[UgcBookmarkItem] = Field(default_factory=list)
    ratings: list[UgcRatingItem] = Field(default_factory=list)
    reviews: list[UgcReviewItem] = Field(default_factory=list)
