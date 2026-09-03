from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class PersonShort(BaseModel):
    id: UUID
    name: str


class GenreShort(BaseModel):
    id: UUID
    name: str


class PersonFilm(BaseModel):
    uuid: UUID
    roles: list[str] = []


class Person(BaseModel):
    id: UUID
    full_name: str
    films: list[PersonFilm] = []


class Genre(BaseModel):
    id: UUID
    name: str
    description: str = ''

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, v) -> str:
        return v.strip() if v else ''


class Movie(BaseModel):
    id: UUID
    imdb_rating: Optional[float] = None
    genres: list[GenreShort] = []
    title: str
    description: str = ''
    directors_names: list[str] = []
    actors_names: list[str] = []
    writers_names: list[str] = []
    directors: list[PersonShort] = []
    actors: list[PersonShort] = []
    writers: list[PersonShort] = []

    @field_validator('title')
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        stripped = v.strip() if v else ''
        if not stripped:
            raise ValueError('title не может быть пустым')
        return stripped

    @field_validator('description', mode='before')
    @classmethod
    def normalize_description(cls, v) -> str:
        return v.strip() if v else ''
