import logging
from http import HTTPStatus
from typing import Optional
from uuid import UUID

from db.auth_client import UserContext
from fastapi import APIRouter, Depends, HTTPException, Query
from models.film import FilmDetail, FilmGenre, FilmPerson, FilmShort
from services.film import FilmService, get_film_service
from services.ugc import UgcCardService, get_ugc_card_service
from ugc_schemas import ReviewWithAuthorSchema

from api.v1.dependencies import PaginationParams, get_optional_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    '/search',
    response_model=list[FilmShort],
    summary="Полнотекстовый поиск фильмов",
    description="Ищет фильмы по названию и описанию. Поддерживает пагинацию.",
    response_description="Список фильмов с названием и рейтингом",
    tags=["Фильмы"],
)
async def films_search(
    query: str = Query(..., description='Поисковый запрос'),
    pagination: PaginationParams = Depends(PaginationParams),
    film_service: FilmService = Depends(get_film_service),
    user: Optional[UserContext] = Depends(get_optional_user),
) -> list[FilmShort]:
    logger.debug(
        'films_search: query=%r user_id=%s', query, user.user_id if user else None
    )
    films = await film_service.search(
        query, pagination.page_number, pagination.page_size
    )
    return [FilmShort(uuid=f.id, title=f.title, imdb_rating=f.rating) for f in films]


@router.get(
    '',
    response_model=list[FilmShort],
    summary="Список фильмов",
    description="Возвращает список фильмов с сортировкой и фильтрацией по жанру. Допустимые поля сортировки: `imdb_rating`, `title`; префикс `-` для убывания.",
    response_description="Список фильмов с названием и рейтингом",
    tags=["Фильмы"],
)
async def films_list(
    sort: str = Query(
        '-imdb_rating',
        pattern=r'^-?(imdb_rating|title)$',
        description='Поле сортировки: imdb_rating или title, префикс - для убывания',
    ),
    genre: Optional[UUID] = Query(None, description='Фильтр по UUID жанра'),
    pagination: PaginationParams = Depends(PaginationParams),
    film_service: FilmService = Depends(get_film_service),
    user: Optional[UserContext] = Depends(get_optional_user),
) -> list[FilmShort]:
    logger.debug('films_list: user_id=%s', user.user_id if user else None)
    films = await film_service.get_list(
        sort=sort,
        genre=str(genre) if genre else None,
        page_number=pagination.page_number,
        page_size=pagination.page_size,
    )
    return [FilmShort(uuid=f.id, title=f.title, imdb_rating=f.rating) for f in films]


@router.get(
    '/{film_id}',
    response_model=FilmDetail,
    summary="Детальная информация о фильме",
    description="Возвращает полную карточку фильма: описание, жанры, актёров, режиссёров и сценаристов.",
    response_description="Детальная карточка фильма",
    tags=["Фильмы"],
)
async def film_details(
    film_id: UUID,
    film_service: FilmService = Depends(get_film_service),
    ugc_service: UgcCardService = Depends(get_ugc_card_service),
    user: Optional[UserContext] = Depends(get_optional_user),
) -> FilmDetail:
    logger.debug(
        'film_details: film_id=%s user_id=%s', film_id, user.user_id if user else None
    )
    film = await film_service.get_by_id(str(film_id))
    if not film:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='film not found')

    # UGC-данные запрашиваются после кэша фильма: рейтинг не должен застывать в Redis
    user_rating, reviews, ugc_available = await ugc_service.get_card_data(film_id)

    return FilmDetail(
        user_rating=user_rating,
        reviews=reviews,
        ugc_available=ugc_available,
        uuid=film.id,
        title=film.title,
        imdb_rating=film.rating,
        description=film.description,
        genre=[FilmGenre(uuid=g.id, name=g.name) for g in film.genres],
        actors=[FilmPerson(uuid=p.id, full_name=p.full_name) for p in film.actors],
        writers=[FilmPerson(uuid=p.id, full_name=p.full_name) for p in film.writers],
        directors=[
            FilmPerson(uuid=p.id, full_name=p.full_name) for p in film.directors
        ],
    )


@router.get(
    '/{film_id}/reviews',
    response_model=list[ReviewWithAuthorSchema],
    summary='Рецензии к фильму',
    description='Рецензии с ФИО авторов, с сортировкой и пагинацией. Недоступность ugc_service — 503.',
    response_description='Список рецензий',
    tags=['Фильмы'],
)
async def film_reviews(
    film_id: UUID,
    sort: str = Query(
        'likes_count',
        pattern=r'^(likes_count|published_at|rating)$',
        description='Поле сортировки',
    ),
    pagination: PaginationParams = Depends(PaginationParams),
    film_service: FilmService = Depends(get_film_service),
    ugc_service: UgcCardService = Depends(get_ugc_card_service),
) -> list[ReviewWithAuthorSchema]:
    film = await film_service.get_by_id(str(film_id))
    if not film:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='film not found')

    reviews = await ugc_service.get_reviews(
        film_id, sort, pagination.page_number, pagination.page_size
    )
    if reviews is None:
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail='ugc_service unavailable'
        )
    return reviews
