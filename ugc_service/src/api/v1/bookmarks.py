"""API endpoints для закладок."""

import logging
from uuid import UUID

from api.dependencies import PaginationParams, get_optional_user
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from services import bookmark_service

router = APIRouter(prefix='/api/v1/bookmarks', tags=['Закладки'])
logger = logging.getLogger(__name__)

EXAMPLE_FILM_ID = UUID('550e8400-e29b-41d4-a716-446655440000')


class BookmarkResponse(BaseModel):
    """Ответ с информацией о закладке."""

    film_id: UUID
    added_at: str


@router.post(
    '',
    status_code=status.HTTP_201_CREATED,
    summary='Добавить закладку',
    description='Добавить фильм в закладки пользователя.',
    response_model=BookmarkResponse,
)
async def add_bookmark(
    film_id: UUID = Query(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
    user = Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    try:
        bookmark = await bookmark_service.add_bookmark(UUID(user.user_id), film_id)
        return BookmarkResponse(
            film_id=bookmark.film_id,
            added_at=bookmark.created_at.isoformat(),
        )
    except Exception as e:
        logger.error('Ошибка добавления закладки: %s', e)
        raise HTTPException(status_code=500, detail='Внутренняя ошибка сервера')


@router.delete(
    '/{film_id}',
    status_code=status.HTTP_204_NO_CONTENT,
    summary='Удалить закладку',
    description='Удалить фильм из закладок пользователя.',
)
async def remove_bookmark(
    film_id: UUID = Path(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
    user = Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    success = await bookmark_service.remove_bookmark(UUID(user.user_id), film_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Закладка не найдена',
        )


@router.get(
    '',
    summary='Список закладок',
    description='Получить список закладок пользователя.',
    response_model=list[BookmarkResponse],
)
async def get_bookmarks(
    pagination: PaginationParams = Depends(PaginationParams),
    user = Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    skip = (pagination.page_number - 1) * pagination.page_size
    bookmarks = await bookmark_service.get_user_bookmarks(
        UUID(user.user_id),
        skip=skip,
        limit=pagination.page_size,
    )

    return [
        BookmarkResponse(
            film_id=b.film_id,
            added_at=b.created_at.isoformat(),
        )
        for b in bookmarks
    ]
