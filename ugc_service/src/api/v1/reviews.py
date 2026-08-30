"""API endpoints для рецензий."""

import logging
from uuid import UUID

from api.dependencies import PaginationParams, get_optional_user
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from services import review_service

router = APIRouter(prefix='/api/v1/reviews', tags=['Рецензии'])
logger = logging.getLogger(__name__)

EXAMPLE_FILM_ID = UUID('550e8400-e29b-41d4-a716-446655440000')
EXAMPLE_REVIEW_ID = UUID('550e8400-e29b-41d4-a716-446655440000')


class ReviewResponse(BaseModel):
    """Ответ с информацией о рецензии."""

    id: str
    user_id: UUID
    film_id: UUID
    title: str
    rating: int
    published_at: str
    likes_count: int
    dislikes_count: int


class ReviewDetailResponse(BaseModel):
    """Детальная информация о рецензии."""

    id: str
    user_id: UUID
    film_id: UUID
    title: str
    text: str
    rating: int
    published_at: str
    likes_count: int
    dislikes_count: int


class ReviewUpdateResponse(BaseModel):
    """Ответ при обновлении рецензии."""

    id: str
    title: str
    updated_at: str


class ReviewVoteResponse(BaseModel):
    """Ответ при голосовании за рецензию."""

    review_id: str
    is_like: bool
    voted_at: str


@router.post(
    '',
    status_code=status.HTTP_201_CREATED,
    summary='Создать рецензию',
    description='Создать рецензию на фильм.',
    response_model=ReviewResponse,
)
async def create_review(
    film_id: UUID = Query(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
    title: str = Query(
        ...,
        min_length=1,
        max_length=200,
        example='Отличный фильм',
        description='Заголовок рецензии',
    ),
    text: str = Query(
        ...,
        min_length=1,
        max_length=10000,
        example='Прекрасная история с глубокими персонажами и отличным сюжетом.',
        description='Текст рецензии',
    ),
    rating: int = Query(
        9,
        ge=0,
        le=10,
        example=9,
        description='Оценка от 0 до 10',
    ),
    user=Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    try:
        review = await review_service.create_review(
            UUID(user.user_id), film_id, title, text, rating
        )
        return ReviewResponse(
            id=str(review.id),
            user_id=review.user_id,
            film_id=review.film_id,
            title=review.title,
            rating=review.rating,
            published_at=review.published_at.isoformat(),
            likes_count=review.likes_count,
            dislikes_count=review.dislikes_count,
        )
    except Exception as e:
        logger.error('Ошибка создания рецензии: %s', e)
        raise HTTPException(status_code=500, detail='Внутренняя ошибка сервера')


@router.get(
    '',
    summary='Список рецензий',
    description='Получить список рецензий к фильму с пагинацией и сортировкой.',
    response_model=list[ReviewResponse],
)
async def get_reviews(
    film_id: UUID = Query(
        ...,
        example=str(EXAMPLE_FILM_ID),
        description='UUID фильма',
    ),
    sort: str = Query(
        'likes_count',
        regex='^(likes_count|published_at|rating)$',
        example='likes_count',
        description='Поле сортировки',
    ),
    pagination: PaginationParams = Depends(PaginationParams),
):
    skip = (pagination.page_number - 1) * pagination.page_size
    reviews = await review_service.get_film_reviews(
        film_id,
        sort_by=sort,
        skip=skip,
        limit=pagination.page_size,
    )

    return [
        ReviewResponse(
            id=str(r.id),
            user_id=r.user_id,
            film_id=r.film_id,
            title=r.title,
            rating=r.rating,
            published_at=r.published_at.isoformat(),
            likes_count=r.likes_count,
            dislikes_count=r.dislikes_count,
        )
        for r in reviews
    ]


@router.get(
    '/{review_id}',
    summary='Детали рецензии',
    description='Получить детальную информацию о рецензии.',
    response_model=ReviewDetailResponse,
)
async def get_review(
    review_id: str = Path(
        ...,
        example='550e8400e29b41d4a7164466',
        description='ObjectId рецензии',
    ),
):
    review = await review_service.get_review_by_id(ObjectId(review_id))
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Рецензия не найдена',
        )

    return ReviewDetailResponse(
        id=str(review.id),
        user_id=review.user_id,
        film_id=review.film_id,
        title=review.title,
        text=review.text,
        rating=review.rating,
        published_at=review.published_at.isoformat(),
        likes_count=review.likes_count,
        dislikes_count=review.dislikes_count,
    )


@router.put(
    '/{review_id}',
    summary='Обновить рецензию',
    description='Обновить рецензию (только автор).',
    response_model=ReviewUpdateResponse,
)
async def update_review(
    review_id: str = Path(
        ...,
        example='550e8400e29b41d4a7164466',
        description='ObjectId рецензии',
    ),
    title: str | None = Query(
        None,
        min_length=1,
        max_length=200,
        example='Отличный фильм (обновлено)',
    ),
    text: str | None = Query(
        None,
        min_length=1,
        max_length=10000,
        example='Обновлённый текст рецензии.',
    ),
    rating: int | None = Query(
        None,
        ge=0,
        le=10,
        example=10,
    ),
    user=Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    review = await review_service.update_review(
        ObjectId(review_id), UUID(user.user_id), title=title, text=text, rating=rating
    )
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Рецензия не найдена или нет прав',
        )

    return ReviewUpdateResponse(
        id=str(review.id),
        title=review.title,
        updated_at=review.published_at.isoformat(),
    )


@router.delete(
    '/{review_id}',
    status_code=status.HTTP_204_NO_CONTENT,
    summary='Удалить рецензию',
    description='Удалить рецензию (только автор).',
)
async def delete_review(
    review_id: str = Path(
        ...,
        example='550e8400e29b41d4a7164466',
        description='ObjectId рецензии',
    ),
    user=Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    success = await review_service.delete_review(
        ObjectId(review_id), UUID(user.user_id)
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Рецензия не найдена или нет прав',
        )


@router.post(
    '/{review_id}/vote',
    summary='Проголосовать за рецензию',
    description='Лайк (is_like=true) или дизлайк (is_like=false).',
    response_model=ReviewVoteResponse,
)
async def vote_on_review(
    review_id: str = Path(
        ...,
        example='550e8400e29b41d4a7164466',
        description='ObjectId рецензии',
    ),
    is_like: bool = Query(
        True,
        example=True,
        description='True = лайк, False = дизлайк',
    ),
    user=Depends(get_optional_user),
):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Требуется авторизация',
        )

    vote = await review_service.vote_on_review(
        UUID(user.user_id), ObjectId(review_id), is_like
    )
    return ReviewVoteResponse(
        review_id=str(vote.review_id),
        is_like=vote.is_like,
        voted_at=vote.created_at.isoformat(),
    )
