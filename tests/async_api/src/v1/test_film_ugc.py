"""Функциональные тесты UGC-блока карточки фильма и эндпоинта рецензий (issue #114).

Проверяют контракт ответа; при поднятом ugc_service ожидается ugc_available=True.
Сценарий недоступности ugc (блок пустой, /reviews → 503) здесь не имитируется:
он покрыт тестом на уровне клиентов, которые требуют отдельного окружения.
"""

import os
import uuid

import pytest

from tests.async_api.settings import test_settings
from tests.async_api.src.v1.test_auth_integration import _is_docker, auth_headers  # noqa: F401

TEST_FILM_UUID = '608c4567-0b8a-49a0-88fb-82770c5b2f61'

UGC_API_HOST = os.getenv('UGC_API_HOST', 'ugc_service' if _is_docker() else '127.0.0.1')
UGC_API_PORT = int(os.getenv('UGC_API_PORT', '8000' if _is_docker() else '8003'))
UGC_BASE_URL = f'http://{UGC_API_HOST}:{UGC_API_PORT}/api/v1'


@pytest.mark.asyncio
async def test_film_card_has_ugc_block(
    es_write_data, es_data_movies, make_get_request
):
    """Карточка содержит user_rating, reviews и ugc_available; imdb_rating не меняется."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', f'/{TEST_FILM_UUID}')

    assert response['status'] == 200
    body = response['body']
    assert body['imdb_rating'] == 8.7
    assert isinstance(body['reviews'], list)
    assert isinstance(body['ugc_available'], bool)
    if body['ugc_available']:
        assert set(body['user_rating']) >= {
            'average_rating',
            'total_ratings',
            'total_likes',
            'total_dislikes',
        }
    else:
        assert body['user_rating'] is None
        assert body['reviews'] == []
    # Анонимный запрос: личные поля всегда отсутствуют/null (S11_T9, issue #116)
    assert body['my_rating'] is None
    assert body['user_has_reviewed'] is False


@pytest.mark.asyncio
async def test_film_card_my_rating_for_authenticated_user(
    es_write_data, es_data_movies, auth_headers, aiohttp_session
):
    """Пользователь, уже оценивший фильм и написавший рецензию, видит
    свою оценку и user_has_reviewed=True в карточке (S11_T9, issue #116)."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    async with aiohttp_session.post(
        f'{UGC_BASE_URL}/likes',
        params={'film_id': TEST_FILM_UUID, 'rating': 9},
        headers=auth_headers,
    ) as response:
        assert response.status == 201, await response.text()

    async with aiohttp_session.post(
        f'{UGC_BASE_URL}/reviews',
        json={
            'film_id': TEST_FILM_UUID,
            'title': 'Моя рецензия',
            'text': 'Текст рецензии для теста S11_T9.',
            'rating': 9,
        },
        headers=auth_headers,
    ) as response:
        assert response.status == 201, await response.text()

    base_url = test_settings.fastapi_settings.get_host()
    async with aiohttp_session.get(
        f'{base_url}/api/v1/films/{TEST_FILM_UUID}',
        headers=auth_headers,
    ) as response:
        assert response.status == 200
        body = await response.json()

    assert body['my_rating'] == 9
    assert body['user_has_reviewed'] is True


@pytest.mark.asyncio
async def test_film_reviews_endpoint_returns_list_or_503(
    es_write_data, es_data_movies, make_get_request
):
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', f'/{TEST_FILM_UUID}/reviews')

    assert response['status'] in (200, 503)
    if response['status'] == 200:
        assert isinstance(response['body'], list)
        for review in response['body']:
            assert 'user_name' in review
            assert 'text' in review
            assert 'author_avatar' not in review


@pytest.mark.asyncio
async def test_film_reviews_unknown_film_returns_404(make_get_request):
    response = await make_get_request('/films', f'/{uuid.uuid4()}/reviews')

    assert response['status'] == 404


@pytest.mark.asyncio
async def test_film_reviews_invalid_sort_returns_422(
    es_write_data, es_data_movies, make_get_request
):
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request(
        '/films', f'/{TEST_FILM_UUID}/reviews', {'sort': 'drop_table'}
    )

    assert response['status'] == 422
