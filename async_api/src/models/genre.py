from uuid import UUID

from pydantic import BaseModel


class GenreResponse(BaseModel):
    uuid: UUID
    name: str
