"""Функциональные тесты для эндпоинта /films."""
import pytest

from tests.async_api.settings import test_settings

TEST_FILM_UUID = '608c4567-0b8a-49a0-88fb-82770c5b2f61'
TEST_FILM_UUID_2 = '708c4567-0b8a-49a0-88fb-82770c5b2f62'

# === Тесты получения фильма по ID ===

@pytest.mark.asyncio
async def test_film_by_id(es_write_data, es_data_movies, make_get_request):
    """Получение фильма по существующему UUID."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', f'/{TEST_FILM_UUID}')

    assert response['status'] == 200
    body = response['body']
    assert body['uuid'] == TEST_FILM_UUID
    assert body['title'] == 'The movie'
    assert body['imdb_rating'] == 8.7


@pytest.mark.asyncio
async def test_film_structure(es_write_data, es_data_movies, make_get_request):
    """Проверка структуры ответа фильма."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', f'/{TEST_FILM_UUID}')

    assert response['status'] == 200
    body = response['body']

    # Обязательные поля
    assert 'uuid' in body
    assert 'title' in body
    assert 'imdb_rating' in body

    # Опциональные поля
    optional_fields = [
        'description', 'genre',  # ✅ 'genre', не 'genres'
        'actors', 'actors_names',
        'writers', 'writers_names',
        'directors', 'directors_names',
    ]
    for field in optional_fields:
        if field in body:
            if field in ['genre', 'actors', 'writers', 'directors',
                         'actors_names', 'writers_names', 'directors_names']:
                assert isinstance(body[field], list)


@pytest.mark.asyncio
async def test_film_nested_data(es_write_data, es_data_movies, make_get_request):
    """Проверка nested-структур (genre, actors, writers, directors)."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', f'/{TEST_FILM_UUID}')

    assert response['status'] == 200
    body = response['body']

    assert 'genre' in body
    assert len(body['genre']) >= 1
    for genre in body['genre']:
        assert 'uuid' in genre
        assert 'name' in genre

    # actors
    assert 'actors' in body
    for actor in body['actors']:
        assert 'uuid' in actor
        assert 'full_name' in actor

    # writers
    assert 'writers' in body
    for writer in body['writers']:
        assert 'uuid' in writer
        assert 'full_name' in writer

    # directors
    assert 'directors' in body
    for director in body['directors']:
        assert 'uuid' in director
        assert 'full_name' in director


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
async def test_film_validation(make_get_request, endpoint, expected_status):
    """Граничные случаи валидации UUID фильма."""
    response = await make_get_request('/films', endpoint)
    assert response['status'] == expected_status


# === Тесты кеширования в Redis ===

@pytest.mark.asyncio
async def test_film_redis_cache(
    es_write_data, es_data_movies, make_get_request, redis_client
):
    """Проверка кеширования фильма в Redis."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    await redis_client.flushdb()
    keys_before = await redis_client.keys('*')
    assert len(keys_before) == 0

    response1 = await make_get_request('/films', f'/{TEST_FILM_UUID}')
    assert response1['status'] == 200

    keys_after = await redis_client.keys('*')
    assert len(keys_after) > 0, "Кеш должен быть заполнен после первого запроса"

    response2 = await make_get_request('/films', f'/{TEST_FILM_UUID}')
    assert response2['status'] == 200
    assert response1['body'] == response2['body']


@pytest.mark.asyncio
async def test_film_cache_invalidation(
    es_write_data, es_data_movies, make_get_request, redis_client
):
    """Проверка, что разные фильмы кешируются отдельно."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)
    await redis_client.flushdb()

    response1 = await make_get_request('/films', f'/{TEST_FILM_UUID}')
    assert response1['status'] == 200

    response2 = await make_get_request('/films', f'/{TEST_FILM_UUID_2}')
    assert response2['status'] == 200

    assert response1['body']['uuid'] != response2['body']['uuid']
    assert response1['body']['title'] != response2['body']['title']


# === Тесты с реальными данными (из ETL) ===
@pytest.mark.asyncio
async def test_film_real_data(make_get_request, es_client, redis_client):
    """Фильм из индекса (данные ETL или синтетика) доступен через API по своему id."""
    await redis_client.flushdb()

    count = await es_client.count(index=test_settings.elastic_settings.es_index_movies)
    if count['count'] == 0:
        pytest.skip("В индексе movies нет данных. Запустите ETL.")

    result = await es_client.search(
        index=test_settings.elastic_settings.es_index_movies,
        body={"size": 1, "query": {"match_all": {}}}
    )

    # Публичный идентификатор фильма — поле id (оно же _id документа);
    # API отдаёт его в ответе под именем uuid.
    film_id = result['hits']['hits'][0]['_source']['id']

    response = await make_get_request('/films', f'/{film_id}')

    assert response['status'] == 200
    assert response['body']['uuid'] == film_id


# === Тесты списка фильмов ===

@pytest.mark.asyncio
async def test_films_list(es_write_data, es_data_movies, make_get_request):
    """Получение списка всех фильмов (GET /api/v1/films)."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', '')

    assert response['status'] == 200
    body = response['body']
    
    assert isinstance(body, list), f"Ожидался список, получен {type(body)}"
    assert len(body) > 0, "Список фильмов не должен быть пустым"
    
    for film in body:
        assert 'uuid' in film or 'id' in film
        assert 'title' in film


@pytest.mark.asyncio
async def test_films_list_pagination(
    es_write_data, es_data_movies, make_get_request
):
    """Пагинация списка фильмов."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response1 = await make_get_request(
        '/films', '', query_data={'page_number': 1, 'page_size': 10}
    )
    assert response1['status'] == 200
    assert len(response1['body']) <= 10

    response2 = await make_get_request(
        '/films', '', query_data={'page_number': 2, 'page_size': 10}
    )
    assert response2['status'] == 200

    ids1 = {f.get('uuid') or f.get('id') for f in response1['body']}
    ids2 = {f.get('uuid') or f.get('id') for f in response2['body']}
    assert not (ids1 & ids2), "Страницы не должны содержать одинаковые фильмы"


# === Тесты поиска фильмов ===

@pytest.mark.asyncio
async def test_films_search(es_write_data, es_data_movies, make_get_request):
    """Поиск фильмов по названию (GET /api/v1/films/search?query=...)."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request(
        '/films', '/search', query_data={'query': 'The movie'}
    )

    assert response['status'] == 200
    body = response['body']
    assert isinstance(body, list)
    assert len(body) > 0, "Поиск 'The movie' должен вернуть результаты"
    
    titles = [f.get('title', '').lower() for f in body]
    assert any('the movie' in t or 'movie' in t for t in titles)


@pytest.mark.asyncio
async def test_films_search_not_found(es_write_data, es_data_movies, make_get_request):
    """Поиск несуществующего фильма."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request(
        '/films', '/search', query_data={'query': 'xyzabc123nonexistent'}
    )

    assert response['status'] == 200
    body = response['body']
    assert isinstance(body, list)
    assert len(body) == 0


@pytest.mark.parametrize(
    'query_data, expected_status',
    [
        # API принимает пустой query и возвращает 200 (пустой список)
        ({'query': ''}, 200),
        # Отсутствует обязательный параметр → 422
        ({}, 422),
        # Валидный запрос с пагинацией
        ({'query': 'The', 'page_number': 1, 'page_size': 10}, 200),
    ],
    ids=['empty_query', 'missing_query', 'with_pagination'],
)
@pytest.mark.asyncio
async def test_films_search_validation(
    es_write_data, es_data_movies, make_get_request,
    query_data, expected_status
):
    """Валидация параметров поиска."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    response = await make_get_request('/films', '/search', query_data=query_data)
    assert response['status'] == expected_status
    
    # Дополнительная проверка для пустого запроса
    if query_data.get('query') == '' and expected_status == 200:
        body = response['body']
        assert isinstance(body, list), "Ответ должен быть списком"


# === Тесты поиска фильмов (дополнительные) ===

@pytest.mark.asyncio
async def test_films_search_pagination(
    es_write_data, es_data_movies, make_get_request
):
    """Проверка пагинации результатов поиска."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    # Запрос первой страницы
    response1 = await make_get_request(
        '/films', '/search', query_data={'query': 'movie', 'page_number': 1, 'page_size': 2}
    )
    assert response1['status'] == 200
    assert len(response1['body']) <= 2

    # Запрос второй страницы
    response2 = await make_get_request(
        '/films', '/search', query_data={'query': 'movie', 'page_number': 2, 'page_size': 2}
    )
    assert response2['status'] == 200
    assert len(response2['body']) <= 2

    # Проверить, что результаты не пересекаются
    ids1 = {f.get('uuid') or f.get('id') for f in response1['body']}
    ids2 = {f.get('uuid') or f.get('id') for f in response2['body']}
    assert not (ids1 & ids2), "Страницы не должны содержать одинаковые фильмы"


@pytest.mark.asyncio
async def test_films_search_case_insensitive(
    es_write_data, es_data_movies, make_get_request
):
    """Проверка регистронезависимости поиска."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    # Поиск в нижнем регистре
    response_lower = await make_get_request(
        '/films', '/search', query_data={'query': 'the movie'}
    )

    # Поиск в верхнем регистре
    response_upper = await make_get_request(
        '/films', '/search', query_data={'query': 'THE MOVIE'}
    )

    assert response_lower['status'] == 200
    assert response_upper['status'] == 200
    
    # Оба запроса должны вернуть результаты
    assert len(response_lower['body']) > 0, "Поиск 'the movie' должен вернуть результаты"
    assert len(response_upper['body']) > 0, "Поиск 'THE MOVIE' должен вернуть результаты"
    
    
@pytest.mark.asyncio
async def test_films_search_partial_match(
    es_write_data, es_data_movies, make_get_request
):
    """Проверка частичного совпадения при поиске."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)
    
    # Поиск 'movie' - должно вернуть фильмы с 'movie' в названии
    response1 = await make_get_request(
        '/films', '/search', query_data={'query': 'movie'}
    )
    assert response1['status'] == 200
    assert len(response1['body']) > 0, "Поиск 'movie' должен вернуть результаты"
    
    # Поиск 'Super' - должно вернуть фильмы с 'Super' в описании (не стоп-слово)
    response2 = await make_get_request(
        '/films', '/search', query_data={'query': 'Super'}
    )
    assert response2['status'] == 200
    assert len(response2['body']) > 0, "Поиск 'Super' должен вернуть результаты"
    
    # Поиск 'World' - должно вернуть фильмы с 'World' в описании
    response3 = await make_get_request(
        '/films', '/search', query_data={'query': 'World'}
    )
    assert response3['status'] == 200
    assert len(response3['body']) > 0, "Поиск 'World' должен вернуть результаты"


@pytest.mark.asyncio
async def test_films_search_description(
    es_write_data, es_data_movies, make_get_request
):
    """Проверка поиска по описанию фильма."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)

    # Поиск 'Super Movie' (из описания)
    response1 = await make_get_request(
        '/films', '/search', query_data={'query': 'Super Movie'}
    )
    assert response1['status'] == 200
    body1 = response1['body']
    assert isinstance(body1, list)

    # Поиск 'World' (из описания 'New World')
    response2 = await make_get_request(
        '/films', '/search', query_data={'query': 'World'}
    )
    assert response2['status'] == 200
    body2 = response2['body']
    assert isinstance(body2, list)


@pytest.mark.asyncio
async def test_films_search_cache(
    es_write_data, es_data_movies, make_get_request, redis_client
):
    """Проверка кеширования результатов поиска в Redis."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)
    await redis_client.flushdb()

    # Выполнить поиск
    response1 = await make_get_request(
        '/films', '/search', query_data={'query': 'The movie'}
    )
    assert response1['status'] == 200

    # Проверить наличие ключа в Redis
    keys = await redis_client.keys('*film:search:*')
    assert len(keys) > 0, "Кеш должен быть заполнен для поиска"

    # Повторить тот же запрос
    response2 = await make_get_request(
        '/films', '/search', query_data={'query': 'The movie'}
    )
    assert response2['status'] == 200

    # Проверить, что результаты идентичны
    assert response1['body'] == response2['body']


@pytest.mark.asyncio
async def test_films_search_caching_invalidation(
    es_write_data, es_data_movies, make_get_request, redis_client
):
    """Проверка, что разные запросы кешируются отдельно."""
    await es_write_data(es_data_movies, test_settings.elastic_settings.es_index_movies)
    await redis_client.flushdb()

    # Выполнить разные запросы
    await make_get_request('/films', '/search', query_data={'query': 'The movie'})
    await make_get_request('/films', '/search', query_data={'query': 'Another movie'})
    await make_get_request('/films', '/search', query_data={'query': 'New'})

    # Проверить, что в Redis создано 3 разных ключа
    keys = await redis_client.keys('*film:search:*')
    assert len(keys) == 3, f"Ожидалось 3 ключа кеша, получено {len(keys)}"

    # Проверить, что результаты различны
    response1 = await make_get_request(
        '/films', '/search', query_data={'query': 'The movie'}
    )
    response2 = await make_get_request(
        '/films', '/search', query_data={'query': 'Another movie'}
    )
    response3 = await make_get_request(
        '/films', '/search', query_data={'query': 'New'}
    )

    assert response1['status'] == 200
    assert response2['status'] == 200
    assert response3['status'] == 200

    # Результаты должны различаться по uuid или title
    uuids1 = {f.get('uuid') for f in response1['body']}
    uuids2 = {f.get('uuid') for f in response2['body']}
    uuids3 = {f.get('uuid') for f in response3['body']}

    # Проверить, что есть хотя бы некоторые различия
    assert uuids1 != uuids2 or uuids1 != uuids3, "Результаты поиска должны различаться"