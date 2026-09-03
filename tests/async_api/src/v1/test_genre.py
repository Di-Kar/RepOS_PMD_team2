"""Функциональные тесты для эндпоинта /genres."""

import pytest

from tests.async_api.settings import test_settings

TEST_GENRE_UUID = '2fec4f4f-7f84-475c-ad28-791ce135bd2e'


# === Тесты получения списка жанров ===


@pytest.mark.asyncio
async def test_genres_list(es_write_data, es_data_genres, make_get_request):
    """Получение списка всех жанров (GET /api/v1/genres)."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    response = await make_get_request('/genres', '')

    assert response['status'] == 200
    body = response['body']

    assert isinstance(body, list), f"Ожидался список, получен {type(body)}"
    assert len(body) > 0, "Список жанров не должен быть пустым"

    for genre in body:
        assert 'uuid' in genre
        assert 'name' in genre


# === Тесты получения жанра по ID ===


@pytest.mark.asyncio
async def test_genre_by_id(es_write_data, es_data_genres, make_get_request):
    """Получение жанра по существующему UUID."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    response = await make_get_request('/genres', f'/{TEST_GENRE_UUID}')

    assert response['status'] == 200
    body = response['body']
    assert body['uuid'] == TEST_GENRE_UUID
    assert body['name'] == 'TestGenre'


@pytest.mark.asyncio
async def test_genre_structure(es_write_data, es_data_genres, make_get_request):
    """Проверка структуры ответа жанра."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    response = await make_get_request('/genres', f'/{TEST_GENRE_UUID}')

    assert response['status'] == 200
    body = response['body']

    # Обязательные поля
    assert 'uuid' in body
    assert 'name' in body


@pytest.mark.asyncio
async def test_genre_not_found(es_write_data, es_data_genres, make_get_request):
    """Попытка получить несуществующий жанр."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    nonexistent_uuid = '00000000-0000-0000-0000-000000000000'
    response = await make_get_request('/genres', f'/{nonexistent_uuid}')

    assert response['status'] == 404


# === Тесты валидации UUID ===


@pytest.mark.parametrize(
    'endpoint, expected_status',
    [
        ('/not-a-uuid', 422),
        ('/abc', 422),
        ('/123', 422),
        ('/invalid-uuid-format', 422),
    ],
    ids=[
        'invalid_uuid_letters',
        'invalid_uuid_short',
        'invalid_uuid_numbers',
        'invalid_uuid_format',
    ],
)
@pytest.mark.asyncio
async def test_genre_validation(make_get_request, endpoint, expected_status):
    """Граничные случаи валидации UUID жанра."""
    response = await make_get_request('/genres', endpoint)
    assert response['status'] == expected_status


# === Тесты кеширования в Redis ===


@pytest.mark.asyncio
async def test_genre_redis_cache(
    es_write_data, es_data_genres, make_get_request, redis_client
):
    """Проверка кеширования жанра в Redis."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)

    await redis_client.flushdb()
    keys_before = await redis_client.keys('*')
    assert len(keys_before) == 0

    response1 = await make_get_request('/genres', f'/{TEST_GENRE_UUID}')
    assert response1['status'] == 200

    keys_after = await redis_client.keys('*')
    assert len(keys_after) > 0, "Кеш должен быть заполнен после первого запроса"

    response2 = await make_get_request('/genres', f'/{TEST_GENRE_UUID}')
    assert response2['status'] == 200
    assert response1['body'] == response2['body']


@pytest.mark.asyncio
async def test_genre_cache_invalidation(
    es_write_data, es_data_genres, make_get_request, redis_client
):
    """Проверка, что разные жанры кешируются отдельно."""
    await es_write_data(es_data_genres, test_settings.elastic_settings.es_index_genres)
    await redis_client.flushdb()

    # Создаем второй фиксированный жанр для теста
    test_genre_uuid_2 = '2fec4f4f-7f84-475c-ad28-791ce135bd2f'

    response1 = await make_get_request('/genres', f'/{TEST_GENRE_UUID}')
    assert response1['status'] == 200

    response2 = await make_get_request('/genres', f'/{test_genre_uuid_2}')
    assert response2['status'] == 200

    assert response1['body']['uuid'] != response2['body']['uuid']
    assert response1['body']['name'] != response2['body']['name']


# === Тесты с реальными данными (из ETL) ===


@pytest.mark.asyncio
async def test_genre_real_data(make_get_request, es_client, redis_client):
    """Жанр из индекса (данные ETL или синтетика) доступен через API по своему id."""
    await redis_client.flushdb()

    count = await es_client.count(index=test_settings.elastic_settings.es_index_genres)
    if count['count'] == 0:
        pytest.skip("В индексе genres нет данных. Запустите ETL.")

    result = await es_client.search(
        index=test_settings.elastic_settings.es_index_genres,
        body={"size": 1, "query": {"match_all": {}}},
    )

    # Публичный идентификатор жанра — поле id (оно же _id документа);
    # API отдаёт его в ответе под именем uuid.
    genre_id = result['hits']['hits'][0]['_source']['id']

    response = await make_get_request('/genres', f'/{genre_id}')

    assert response['status'] == 200
    body = response['body']
    assert body['uuid'] == genre_id
    assert 'name' in body


@pytest.mark.asyncio
async def test_genres_list_real_data(make_get_request, es_client, redis_client):
    """Получение списка жанров из реальных данных (после работы ETL)."""
    await redis_client.flushdb()

    count = await es_client.count(index=test_settings.elastic_settings.es_index_genres)
    if count['count'] == 0:
        pytest.skip("В индексе genres нет данных. Запустите ETL.")

    response = await make_get_request('/genres', '')

    assert response['status'] == 200
    body = response['body']
    assert isinstance(body, list), "Ответ должен быть списком"
    assert len(body) > 0, "Список жанров не должен быть пустым"

    for genre in body:
        assert 'uuid' in genre
        assert 'name' in genre
