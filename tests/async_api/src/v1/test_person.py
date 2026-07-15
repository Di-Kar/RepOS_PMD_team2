"""Функциональные тесты для эндпоинта /persons."""
import pytest

from tests.async_api.settings import test_settings

TEST_PERSON_UUID = '3a6ed55e-6aef-4cd2-932c-808495182425'
TEST_PERSON_UUID_2 = '4a6ed55e-6aef-4cd2-932c-808495182426'

# === Тесты получения персоны по ID ===
@pytest.mark.asyncio
async def test_person_by_id(es_write_data, es_data_persons, make_get_request):
    """Получение персоны по существующему UUID."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')

    assert response['status'] == 200
    body = response['body']
    assert body['uuid'] == TEST_PERSON_UUID
    assert body['full_name'] == 'James'


@pytest.mark.asyncio
async def test_person_structure(es_write_data, es_data_persons, make_get_request):
    """Проверка структуры ответа персоны."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')

    assert response['status'] == 200
    body = response['body']

    # Обязательные поля
    assert 'uuid' in body
    assert 'full_name' in body

    # Опциональные поля
    if 'films' in body:
        assert isinstance(body['films'], list)
        for film in body['films']:
            assert 'uuid' in film
            assert 'roles' in film
            assert isinstance(film['roles'], list)


@pytest.mark.asyncio
async def test_person_films(
    es_write_data, es_data_persons, es_data_movies, make_get_request, redis_client
):
    """Проверка вложенных фильмов (films) персоны.

    API строит films не из документа персоны, а агрегацией по индексу movies
    (nested-запросы по actors/directors/writers.id), поэтому заполняем оба
    индекса: в movies фильм 608c... ссылается на James как актёра и режиссёра.
    """
    # Сбрасываем кэш: предыдущие тесты могли закэшировать персону без films
    await redis_client.flushdb()
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')
    assert response['status'] == 200
    body = response['body']

    assert body.get('films'), "API должен агрегировать films персоны из индекса movies"
    film_uuids = [film['uuid'] for film in body['films']]
    assert '608c4567-0b8a-49a0-88fb-82770c5b2f61' in film_uuids

    for film in body['films']:
        assert 'uuid' in film
        assert 'roles' in film
        assert all(isinstance(r, str) for r in film['roles'])

# === Тесты валидации UUID ===
@pytest.mark.parametrize(
    'endpoint, expected_status',
    [
        ('/00000000-0000-0000-0000-000000000000', 404),
        ('/not-a-uuid', 422),
        ('/abc', 422),
        ('/123', 422),
    ],
    ids=[
        'nonexistent_uuid',
        'invalid_uuid_letters',
        'invalid_uuid_short',
        'invalid_uuid_numbers',
    ],
)
@pytest.mark.asyncio
async def test_person_validation(make_get_request, endpoint, expected_status):
    """Граничные случаи валидации UUID персоны."""
    response = await make_get_request('/persons', endpoint)
    assert response['status'] == expected_status


# === Тесты кеширования в Redis ===

@pytest.mark.asyncio
async def test_person_redis_cache(
    es_write_data, es_data_persons, make_get_request, redis_client
):
    """Проверка кеширования персоны в Redis."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    await redis_client.flushdb()
    keys_before = await redis_client.keys('*')
    assert len(keys_before) == 0

    response1 = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')
    assert response1['status'] == 200

    keys_after = await redis_client.keys('*')
    assert len(keys_after) > 0, "Кеш должен быть заполнен после первого запроса"

    response2 = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')
    assert response2['status'] == 200
    assert response1['body'] == response2['body']


@pytest.mark.asyncio
async def test_person_cache_invalidation(
    es_write_data, es_data_persons, make_get_request, redis_client
):
    """Проверка, что разные персоны кешируются отдельно."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)
    await redis_client.flushdb()

    response1 = await make_get_request('/persons', f'/{TEST_PERSON_UUID}')
    assert response1['status'] == 200

    response2 = await make_get_request('/persons', f'/{TEST_PERSON_UUID_2}')
    assert response2['status'] == 200

    assert response1['body']['uuid'] != response2['body']['uuid']
    assert response1['body']['full_name'] != response2['body']['full_name']

# === Тесты с реальными данными (из ETL) ===
@pytest.mark.asyncio
async def test_person_real_data(make_get_request, es_client, redis_client):
    """Персона из индекса (данные ETL или синтетика) доступна через API по своему id."""
    await redis_client.flushdb()

    count = await es_client.count(index=test_settings.elastic_settings.es_index_persons)
    if count['count'] == 0:
        pytest.skip("В индексе persons нет данных. Запустите ETL.")

    result = await es_client.search(
        index=test_settings.elastic_settings.es_index_persons,
        body={"size": 1, "query": {"match_all": {}}}
    )

    # Публичный идентификатор персоны — поле id (оно же _id документа);
    # API отдаёт его в ответе под именем uuid.
    person_id = result['hits']['hits'][0]['_source']['id']

    response = await make_get_request('/persons', f'/{person_id}')

    assert response['status'] == 200
    assert response['body']['uuid'] == person_id

# === Тесты поиска персон ===
@pytest.mark.asyncio
async def test_persons_search(es_write_data, es_data_persons, make_get_request):
    """Поиск персон по имени (GET /api/v1/persons/search?query=...)."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request(
        '/persons', '/search', query_data={'query': 'James'}
    )

    assert response['status'] == 200
    body = response['body']
    assert isinstance(body, list)
    assert len(body) > 0, "Поиск 'James' должен вернуть результаты"
    
    names = [p.get('full_name', '').lower() for p in body]
    assert any('james' in n for n in names)


@pytest.mark.asyncio
async def test_persons_search_not_found(es_write_data, es_data_persons, make_get_request):
    """Поиск несуществующей персоны."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request(
        '/persons', '/search', query_data={'query': 'xyzabc123nonexistent'}
    )

    assert response['status'] == 200
    body = response['body']
    assert isinstance(body, list)
    assert len(body) == 0


@pytest.mark.parametrize(
    'query_data, expected_status',
    [
        ({'query': ''}, 200),
        ({}, 422),
        ({'query': 'Stan', 'page_number': 1, 'page_size': 10}, 200),
    ],
    ids=['empty_query', 'missing_query', 'with_pagination'],
)
@pytest.mark.asyncio
async def test_persons_search_validation(
    es_write_data, es_data_persons, make_get_request,
    query_data, expected_status
):
    """Валидация параметров поиска."""
    await es_write_data(es_data_persons, test_settings.elastic_settings.es_index_persons)

    response = await make_get_request('/persons', '/search', query_data=query_data)
    assert response['status'] == expected_status
    
    if query_data.get('query') == '' and expected_status == 200:
        body = response['body']
        assert isinstance(body, list), "Ответ должен быть списком"
