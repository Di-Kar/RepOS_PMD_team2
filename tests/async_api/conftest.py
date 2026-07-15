"""Общие фикстуры для функциональных тестов."""
import uuid

import aiohttp
from elasticsearch import AsyncElasticsearch
import pytest_asyncio
from elasticsearch.helpers import async_bulk
from redis.asyncio import Redis

from .settings import test_settings


@pytest_asyncio.fixture(name='es_client', scope='function')
async def es_client():
    """Клиент Elasticsearch."""
    client = AsyncElasticsearch(
        hosts=test_settings.elastic_settings.get_host(),
        verify_certs=False,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(name='redis_client', scope='function')
async def redis_client():
    """Клиент Redis."""
    client = Redis(
        host=test_settings.redis_settings.host,
        port=test_settings.redis_settings.port,
        decode_responses=True,
    )
    yield client
    await client.aclose()


@pytest_asyncio.fixture(name='aiohttp_session', scope='function')
async def aiohttp_session():
    """HTTP-сессия."""
    session = aiohttp.ClientSession()
    yield session
    await session.close()


@pytest_asyncio.fixture(name='make_get_request', scope='function')
async def make_get_request(aiohttp_session):
    async def inner(field: str, endpoint: str, query_data=None):
        if query_data is None:
            query_data = {}
        
        base_url = test_settings.fastapi_settings.get_host()
        url = f"{base_url}/api/v1{field}{endpoint}"
        while '//' in url.replace('://', ''):
            url = url.replace('//', '/')
       
        async with aiohttp_session.get(url, params=query_data) as response:
            try:
                body = await response.json()
            except Exception:
                body = await response.text()
            status = response.status
        
        return {"body": body, "status": status}
    return inner


@pytest_asyncio.fixture(name='es_write_data', scope='function')
async def es_write_data(es_client):
    """Фикстура для записи тестовых данных в Elasticsearch."""
    async def inner(data, es_index):
        # ✅ Удаляем индекс, если он существует
        if await es_client.indices.exists(index=es_index):
            await es_client.indices.delete(index=es_index)
            # ✅ Ждём, пока индекс реально удалится (асинхронная операция)
            import asyncio
            await asyncio.sleep(1.0)
        
        # ✅ Создаём индекс с обработкой race condition
        mapping = test_settings.es_index_mapping(es_index)
        try:
            await es_client.indices.create(
                index=es_index,
                settings=mapping.get('settings'),
                mappings=mapping.get('mappings'),
            )
        except Exception as e:
            # ✅ Если индекс уже существует (race condition) — игнорируем
            if 'resource_already_exists_exception' in str(e):
                # Удаляем и создаём заново
                await es_client.indices.delete(index=es_index, ignore=[404])
                await asyncio.sleep(0.5)
                await es_client.indices.create(
                    index=es_index,
                    settings=mapping.get('settings'),
                    mappings=mapping.get('mappings'),
                )
            else:
                raise
        
        # ✅ Записываем данные
        updated, errors = await async_bulk(
            client=es_client,
            actions=data,
            raise_on_error=True,
        )
        
        # ✅ Refresh индекса, чтобы данные сразу стали доступны для поиска
        await es_client.indices.refresh(index=es_index)
        
        if errors:
            raise Exception('Ошибка записи данных в Elasticsearch')
    
    return inner


@pytest_asyncio.fixture(name='es_data_movies', scope='function')
async def es_data_movies():
    """Тестовые данные для фильмов."""
    es_data = [{
        'id': str(uuid.uuid4()),
        'uuid': str(uuid.uuid4()),
        'imdb_rating': 8.5,
        'title': 'The Star',
        'description': 'New World',
        'genres': [
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'name': 'Action'},
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'name': 'Sci-Fi'}
        ],
        'directors': [{'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Stan'}],
        'actors': [
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Ann'},
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Bob'}
        ],
        'writers': [
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Ben'},
            {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Howard'}
        ],
        'directors_names': ['Stan'],
        'actors_names': ['Ann', 'Bob'],
        'writers_names': ['Ben', 'Howard']
    } for _ in range(60)] + [
        {
            'id': '608c4567-0b8a-49a0-88fb-82770c5b2f61',
            'uuid': '608c4567-0b8a-49a0-88fb-82770c5b2f61',
            'imdb_rating': 8.7,
            'title': 'The movie',
            'description': 'New Super Movie',
            'genres': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'name': 'Action'},
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'name': 'Sci-Fi'},
                {'id': '2fec4f4f-7f84-475c-ad28-791ce135bd2e', 'uuid': '2fec4f4f-7f84-475c-ad28-791ce135bd2e', 'name': 'TestGenre'}
            ],
            'directors': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Stan'},
                # Фиксированная персона James: API агрегирует films персоны по индексу movies,
                # на эту связь опирается test_person_films
                {'id': '3a6ed55e-6aef-4cd2-932c-808495182425', 'uuid': '3a6ed55e-6aef-4cd2-932c-808495182425', 'full_name': 'James'}
            ],
            'actors': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Ann'},
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Bob'},
                {'id': '88c78458-54c8-455f-846e-82734dc1967f', 'uuid': '88c78458-54c8-455f-846e-82734dc1967f', 'full_name': 'Maxim'},
                {'id': '3a6ed55e-6aef-4cd2-932c-808495182425', 'uuid': '3a6ed55e-6aef-4cd2-932c-808495182425', 'full_name': 'James'}
            ],
            'writers': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Ben'},
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Howard'}
            ],
            'directors_names': ['Stan'],
            'actors_names': ['Ann', 'Bob', 'Maxim'],
            'writers_names': ['Ben', 'Howard']
        },
        {
            'id': '708c4567-0b8a-49a0-88fb-82770c5b2f62',
            'uuid': '708c4567-0b8a-49a0-88fb-82770c5b2f62',
            'imdb_rating': 9.1,
            'title': 'Another movie',
            'description': 'Second Super Movie',
            'genres': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'name': 'Drama'},
            ],
            'directors': [{'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'James'}],
            'actors': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Alice'},
            ],
            'writers': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'full_name': 'Charlie'},
            ],
            'directors_names': ['James'],
            'actors_names': ['Alice'],
            'writers_names': ['Charlie']
        }
    ]

    bulk_query = []
    for row in es_data:
        data = {'_index': 'movies', '_id': row['id']}
        data.update({'_source': row})
        bulk_query.append(data)
    return bulk_query


@pytest_asyncio.fixture(name='es_data_genres', scope='function')
async def es_data_genres():
    """Тестовые данные для жанров."""
    es_data = [
        {'id': str(uuid.uuid4()), 'name': 'Action'},
        {'id': str(uuid.uuid4()), 'name': 'Sci-Fi'},
        {'id': '2fec4f4f-7f84-475c-ad28-791ce135bd2e', 'name': 'TestGenre'},
        {'id': '2fec4f4f-7f84-475c-ad28-791ce135bd2f', 'name': 'TestGenre2'},
    ]
    bulk_query = []
    for row in es_data:
        data = {'_index': 'genres', '_id': row['id']}
        data.update({'_source': row})
        bulk_query.append(data)
    return bulk_query


@pytest_asyncio.fixture(name='es_data_persons', scope='function')
async def es_data_persons():
    """Тестовые данные для персон."""
    es_data = [{
        'id': str(uuid.uuid4()),
        'uuid': str(uuid.uuid4()),
        'full_name': f'{person} {str(uuid.uuid4())}',
        'films': [{'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'roles': ['actor']}]
    } for person in ['Ann', 'Bob', 'Ben', 'Howard', 'Stan'] * 10] + [
        {
            # ✅ Первая фиксированная персона
            'id': '3a6ed55e-6aef-4cd2-932c-808495182425',
            'uuid': '3a6ed55e-6aef-4cd2-932c-808495182425',
            'full_name': 'James',
            'films': [
                {'id': '608c4567-0b8a-49a0-88fb-82770c5b2f61', 'uuid': '608c4567-0b8a-49a0-88fb-82770c5b2f61', 'roles': ['actor', 'director']}
            ]
        },
        {
            # ✅ Вторая фиксированная персона (для cache_invalidation)
            'id': '4a6ed55e-6aef-4cd2-932c-808495182426',
            'uuid': '4a6ed55e-6aef-4cd2-932c-808495182426',
            'full_name': 'Alice',
            'films': [
                {'id': str(uuid.uuid4()), 'uuid': str(uuid.uuid4()), 'roles': ['writer']}
            ]
        }
    ]

    bulk_query = []
    for row in es_data:
        data = {'_index': 'persons', '_id': row['id']}
        data.update({'_source': row})
        bulk_query.append(data)
    return bulk_query


@pytest_asyncio.fixture(name='check_data_exists', scope='function')
async def check_data_exists(es_client):
    """Проверка наличия данных в индексе."""
    async def inner(index: str, min_count: int = 1):
        count = await es_client.count(index=index)
        actual_count = count['count']
        assert actual_count >= min_count, (
            f"В индексе '{index}' найдено {actual_count} документов, "
            f"ожидалось минимум {min_count}."
        )
        return actual_count
    return inner

@pytest_asyncio.fixture(name='get_random_doc', scope='function')
async def get_random_doc(es_client):
    """Получение случайного документа из индекса."""
    async def inner(index: str):
        result = await es_client.search(
            index=index,
            body={"size": 1, "query": {"match_all": {}}}
        )
        if result['hits']['hits']:
            return result['hits']['hits'][0]['_source']
        return None
    return inner

@pytest_asyncio.fixture(name='clean_redis', scope='function')
async def clean_redis(redis_client):
    """Очистка Redis перед тестом."""
    await redis_client.flushdb()
    yield redis_client
    await redis_client.flushdb()
