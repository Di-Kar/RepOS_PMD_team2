"""API endpoints для лайков."""

import logging
from uuid import UUID

from api.dependencies import get_optional_user
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from services import like_service

router = APIRouter(prefix='/api/v1/likes', tags=['Лайки'])
logger = logging.getLogger(__name__)

EXAMPLE_FILM_ID = UUID('550e8400-e29b-41d4-a716-446655440000')


@router.post(
    '',
    status_code=status.HTTP_201_CREATED,
    summary='Добавить/обновить лайк',
    description='Добавить или обновить оценку фильма (0-10).',
)
async def add_like(
    film_id: UUID = Query(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
    rating: int = Query(
        8,
        ge=0,
        le=10,
        example=8,
        description='Оценка от 0 (дизлайк) до 10 (лайк)',
    ),
    user = Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    try:
        like = await like_service.add_or_update_like(
            UUID(user.user_id), film_id, rating
        )
        return {
            'film_id': str(like.film_id),
            'rating': like.rating,
            'updated_at': like.updated_at.isoformat(),
        }
    except Exception as e:
        logger.error('Ошибка добавления лайка: %s', e)
        raise HTTPException(status_code=500, detail='Внутренняя ошибка сервера')


@router.delete(
    '/{film_id}',
    status_code=status.HTTP_204_NO_CONTENT,
    summary='Удалить лайк',
    description='Удалить оценку фильма.',
)
async def remove_like(
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

    success = await like_service.remove_like(UUID(user.user_id), film_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Лайк не найден',
        )


@router.get(
    '/{film_id}',
    summary='Статистика лайков',
    description='Получить статистику лайков для фильма.',
)
async def get_like_stats(
    film_id: UUID = Path(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
):
    stats = await like_service.get_film_like_stats(film_id)
    return stats
