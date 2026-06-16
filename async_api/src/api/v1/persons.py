from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from api.v1.dependencies import PaginationParams
from models.film import FilmShort
from models.person import PersonFilmResponse, PersonResponse, PersonSearchResponse
from services.person import PersonService, get_person_service

router = APIRouter()


@router.get(
    '/search',
    response_model=list[PersonSearchResponse],
    summary="Полнотекстовый поиск персон",
    description="Ищет персон (актёров, режиссёров, сценаристов) по имени. Поддерживает пагинацию. "
                "⚠️ Фильмография в этом запросе не включена. Для получения полной информации используйте `/persons/{id}`.",
    response_description="Список персон с именем и UUID (без фильмографии)",
    tags=["Персоны"],
)
async def persons_search(
    query: str = Query(..., description='Поисковый запрос'),
    pagination: PaginationParams = Depends(PaginationParams),
    person_service: PersonService = Depends(get_person_service),
) -> list[PersonSearchResponse]:
    persons = await person_service.search(query, pagination.page_number, pagination.page_size)
    return [
        PersonSearchResponse(
            uuid=p.id,
            full_name=p.full_name,
        )
        for p in persons
    ]


@router.get(
    '/{person_id}',
    response_model=PersonResponse,
    summary="Персона по ID",
    description="Возвращает информацию о персоне по UUID: имя и список фильмов с ролями.",
    response_description="Персона с именем и фильмографией",
    tags=["Персоны"],
)
async def person_details(
    person_id: UUID,
    person_service: PersonService = Depends(get_person_service),
) -> PersonResponse:
    person = await person_service.get_by_id(str(person_id))
    if not person:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='person not found')
    return PersonResponse(
        uuid=person.id,
        full_name=person.full_name,
        films=[PersonFilmResponse(uuid=pf.uuid, roles=pf.roles) for pf in person.films],
    )


@router.get(
    '/{person_id}/film',
    response_model=list[FilmShort],
    summary="Фильмы персоны",
    description="Возвращает список фильмов, в которых участвовала персона.",
    response_description="Список фильмов с названием и рейтингом",
    tags=["Персоны"],
)
async def person_films(
    person_id: UUID,
    person_service: PersonService = Depends(get_person_service),
) -> list[FilmShort]:
    films = await person_service.get_films_by_person(str(person_id))
    if films is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='person not found')
    return [FilmShort(uuid=f['uuid'], title=f['title'], imdb_rating=f.get('imdb_rating')) for f in films]
