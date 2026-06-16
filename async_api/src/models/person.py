from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


class PersonFilmES(BaseModel):
    uuid: UUID
    roles: list[str] = []


class PersonES(BaseModel):
    id: UUID
    full_name: str
    films: list[PersonFilmES] = []

    @model_validator(mode='before')
    @classmethod
    def normalize_full_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and 'full_name' not in data and 'name' in data:
            data = dict(data)
            data['full_name'] = data['name']
        return data


class PersonFilmResponse(BaseModel):
    uuid: UUID
    roles: list[str] = []


class PersonResponse(BaseModel):
    uuid: UUID
    full_name: str
    films: list[PersonFilmResponse] = []


class PersonSearchResponse(BaseModel):
    uuid: UUID
    full_name: str