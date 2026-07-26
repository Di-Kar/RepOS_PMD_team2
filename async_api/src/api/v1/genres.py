from http import HTTPStatus
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.v1.dependencies import get_optional_user
from db.auth_client import UserContext
from models.genre import GenreResponse
from services.genre import GenreService, get_genre_service

router = APIRouter()


@router.get(
    '',
    response_model=list[GenreResponse],
    summary="Список жанров",
    description="Возвращает все доступные жанры.",
    response_description="Список жанров с UUID и названием",
    tags=["Жанры"],
)
async def genres_list(
    genre_service: GenreService = Depends(get_genre_service),
    user: Optional[UserContext] = Depends(get_optional_user),
) -> list[GenreResponse]:
    genres = await genre_service.get_list()
    return [GenreResponse(uuid=g.id, name=g.name) for g in genres]


@router.get(
    '/{genre_id}',
    response_model=GenreResponse,
    summary="Жанр по ID",
    description="Возвращает жанр по его UUID.",
    response_description="Жанр с UUID и названием",
    tags=["Жанры"],
)
async def genre_details(
    genre_id: UUID,
    genre_service: GenreService = Depends(get_genre_service),
    user: Optional[UserContext] = Depends(get_optional_user),
) -> GenreResponse:
    genre = await genre_service.get_by_id(str(genre_id))
    if not genre:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='genre not found')
    return GenreResponse(uuid=genre.id, name=genre.name)
