from uuid import UUID
from typing import Optional, Any
from pydantic import BaseModel, model_validator


class FilmShort(BaseModel):
    uuid: UUID
    title: str
    imdb_rating: Optional[float] = None


class FilmPerson(BaseModel):
    uuid: UUID
    full_name: str


class FilmGenre(BaseModel):
    uuid: UUID
    name: str


class FilmDetail(BaseModel):
    uuid: UUID
    title: str
    imdb_rating: Optional[float] = None
    description: Optional[str] = None
    genre: list[FilmGenre] = []
    actors: list[FilmPerson] = []
    writers: list[FilmPerson] = []
    directors: list[FilmPerson] = []


class Genre(BaseModel):
    id: UUID
    name: str


class FilmActorES(BaseModel):
    id: UUID
    full_name: str

    @model_validator(mode='before')
    @classmethod
    def normalize_full_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'full_name' not in data and 'name' in data:
            data = dict(data)
            data['full_name'] = data['name']
        return data


class Film(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    rating: Optional[float] = None
    imdb_rating: Optional[float] = None
    type: str = ''
    genres: list[Genre] = []
    actors: list[FilmActorES] = []
    writers: list[FilmActorES] = []
    directors: list[FilmActorES] = []

    @model_validator(mode='before')
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # rating может быть в поле imdb_rating
        if 'rating' not in data or data['rating'] is None:
            data['rating'] = data.get('imdb_rating')
        return data
