"""Internal (S2S) роуты ugc_service (S11_T6, issue #113) — агрегирующая
витрина профиля в user_profiles дёргает эту ручку вместо self-service
эндпоинтов bookmarks/likes/reviews, которые отдают данные только владельцу
Bearer-токена и не позволяют запросить произвольный user_id. Авторизация —
X-Internal-Api-Key, см. api/dependencies.py:verify_internal_api_key."""

import asyncio
import logging
from uuid import UUID

from api.dependencies import verify_internal_api_key
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from services import bookmark_service, like_service, review_service

logger = logging.getLogger(__name__)

from .bookmarks import BookmarkResponse  # noqa: E402
from .reviews import ReviewResponse  # noqa: E402

router = APIRouter(
    prefix='/api/v1/internal',
    tags=['Internal'],
    dependencies=[Depends(verify_internal_api_key)],
)


class LikeResponse(BaseModel):
    """Оценка, выставленная пользователем фильму."""

    film_id: UUID
    rating: int
    updated_at: str


class UserUgcSummaryResponse(BaseModel):
    """Сводка UGC-данных пользователя для /api/v1/profiles/{user_id}/full."""

    bookmarks: list[BookmarkResponse]
    ratings: list[LikeResponse]
    reviews: list[ReviewResponse]


@router.get(
    '/users/{user_id}/ugc-summary',
    summary='Сводка UGC-данных пользователя',
    description='Закладки, оценки и рецензии пользователя одним ответом — '
    'для агрегирующей витрины профиля (user_profiles).',
    response_model=UserUgcSummaryResponse,
)
async def get_user_ugc_summary(
    user_id: UUID,
    limit: int = Query(20, ge=1, le=100, description='Макс. элементов на список'),
) -> UserUgcSummaryResponse:
    # return_exceptions=True: сбой одного из трёх независимых запросов к
    # Mongo (например, временный таймаут только на коллекции reviews) не
    # должен обрушивать весь ответ — отдаём то, что получилось, а для
    # сбойного источника пустой список (не хуже недоступности ugc_service
    # целиком, которую user_profiles уже умеет переживать).
    names = ('bookmarks', 'likes', 'reviews')
    results = await asyncio.gather(
        bookmark_service.get_user_bookmarks(user_id, limit=limit),
        like_service.get_user_likes(user_id, limit=limit),
        review_service.get_user_reviews(user_id, limit=limit),
        return_exceptions=True,
    )
    bookmarks, likes, reviews = (
        [] if isinstance(result, BaseException) else result for result in results
    )
    for name, result in zip(names, results):
        if isinstance(result, BaseException):
            logger.warning(
                'Не удалось получить %s для user_id=%s: %s', name, user_id, result
            )

    return UserUgcSummaryResponse(
        bookmarks=[
            BookmarkResponse(film_id=b.film_id, added_at=b.created_at.isoformat())
            for b in bookmarks
        ],
        ratings=[
            LikeResponse(
                film_id=like.film_id,
                rating=like.rating,
                updated_at=like.updated_at.isoformat(),
            )
            for like in likes
        ],
        reviews=[
            ReviewResponse(
                id=str(r.id),
                user_id=r.user_id,
                film_id=r.film_id,
                title=r.title,
                text=r.text,
                rating=r.rating,
                published_at=r.published_at.isoformat(),
                likes_count=r.likes_count,
                dislikes_count=r.dislikes_count,
            )
            for r in reviews
        ],
    )
