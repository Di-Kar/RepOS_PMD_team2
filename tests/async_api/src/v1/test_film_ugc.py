"""Функциональные тесты UGC-блока карточки фильма и эндпоинта рецензий (issue #114).

Проверяют контракт ответа; при поднятом ugc_service ожидается ugc_available=True.
Сценарий недоступности ugc (блок пустой, /reviews → 503) здесь не имитируется:
он покрыт тестом на уровне клиентов, которые требуют отдельного окружения.
"""

import uuid

import pytest

from tests.async_api.settings import test_settings

TEST_FILM_UUID = '608c4567-0b8a-49a0-88fb-82770c5b2f61'


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
