"""E2E тесты для ugc_service — проверка всех API endpoints и данных в MongoDB."""

import asyncio
import os
from uuid import uuid4

import aiohttp
import pytest
from bson import Binary, ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

# ==================================================================== #
#  Фикстуры event loop                                                   #
# ==================================================================== #


@pytest.fixture(scope='session')
def event_loop():
    """Event loop на уровне сессии для session-scoped фикстур."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==================================================================== #
#  Утилиты                                                               #
# ==================================================================== #


def _encode_uuid(uuid_obj):
    """Кодирует Python UUID в BSON Binary для MongoDB."""
    return Binary.from_uuid(uuid_obj)


def _to_objectid(obj_id_str):
    """Конвертирует ObjectId string в BSON ObjectId."""
    return ObjectId(obj_id_str)


# ==================================================================== #
#  Настройки                                                             #
# ==================================================================== #

UGC_API_HOST = os.getenv('UGC_API_HOST', 'ugc_service')
UGC_API_PORT = int(os.getenv('UGC_API_PORT', '8000'))
UGC_BASE_URL = f'http://{UGC_API_HOST}:{UGC_API_PORT}'

AUTH_API_HOST = os.getenv('AUTH_API_HOST', 'auth_service')
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000'))
AUTH_BASE_URL = f'http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1/auth'

MONGO_HOST = os.getenv('MONGO_HOST', 'mongo_mongos-0')
MONGO_PORT = int(os.getenv('MONGO_PORT', '27017'))
MONGO_URL = f'mongodb://{MONGO_HOST}:{MONGO_PORT}'
MONGO_DB = 'ugc_service'


# ==================================================================== #
#  Фикстуры                                                              #
# ==================================================================== #


@pytest.fixture(scope='function')
async def mongo_client():
    """Клиент MongoDB."""
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    await client.admin.command('ping')
    db = client.get_database(MONGO_DB)
    yield db
    client.close()


@pytest.fixture(scope='session')
async def aiohttp_session():
    """HTTP-сессия."""
    session = aiohttp.ClientSession()
    yield session
    await session.close()


@pytest.fixture(scope='function')
async def clean_collections(mongo_client):
    """Очистка всех коллекций перед тестом."""
    collections = ['bookmarks', 'likes', 'reviews', 'review_votes']
    for col in collections:
        await mongo_client[col].delete_many({})
    yield
    for col in collections:
        await mongo_client[col].delete_many({})


@pytest.fixture(scope='session')
async def test_user_id(aiohttp_session):
    """Получение user_id из auth_service для тестов."""
    async with aiohttp_session.get(
        f'{AUTH_BASE_URL}/profile',
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get('id')
    return None


@pytest.fixture(scope='session')
async def auth_token(aiohttp_session):
    """Получение тестового JWT-токена через auth_service (один раз на сессию)."""
    # Сначала регистрируем
    async with aiohttp_session.post(
        f'{AUTH_BASE_URL}/register',
        json={
            'email': 'test_e2e@example.com',
            'password': 'TestPass123!',
            'full_name': 'Тестовый Пользователь',
        },
    ) as resp:
        pass  # 200 — успешно, 409 — уже существует
    
    # Теперь логинимся
    async with aiohttp_session.post(
        f'{AUTH_BASE_URL}/login',
        json={
            'email': 'test_e2e@example.com',
            'password': 'TestPass123!',
        },
    ) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get('access_token')
    
    return None


@pytest.fixture(scope='function')
async def auth_headers(auth_token):
    """Заголовки с токеном авторизации."""
    if auth_token:
        return {'Authorization': f'Bearer {auth_token}'}
    return {}


# ==================================================================== #
#  Тесты закладок                                                        #
# ==================================================================== #


class TestBookmarksE2E:
    """E2E тесты для закладок."""

    async def test_add_bookmark(self, aiohttp_session, clean_collections, auth_headers):
        """Добавление закладки."""
        film_id = uuid4()

        async with aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/bookmarks',
            params={'film_id': str(film_id)},
            headers=auth_headers,
        ) as resp:
            assert resp.status == 201, f"Expected 201, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert 'film_id' in data
            assert data['film_id'] == str(film_id)
            assert 'added_at' in data

    async def test_get_bookmarks(self, aiohttp_session, clean_collections, auth_headers):
        """Получение списка закладок."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/bookmarks',
            params={'film_id': str(film_id)},
            headers=auth_headers,
        )

        async with aiohttp_session.get(
            f'{UGC_BASE_URL}/api/v1/bookmarks',
            headers=auth_headers,
        ) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert data[0]['film_id'] == str(film_id)

    async def test_remove_bookmark(self, aiohttp_session, clean_collections, auth_headers):
        """Удаление закладки."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/bookmarks',
            params={'film_id': str(film_id)},
            headers=auth_headers,
        )

        async with aiohttp_session.delete(
            f'{UGC_BASE_URL}/api/v1/bookmarks/{film_id}',
            headers=auth_headers,
        ) as resp:
            assert resp.status == 204

    async def test_bookmark_exists_in_mongodb(self, aiohttp_session, clean_collections, mongo_client, auth_headers, test_user_id):
        """Проверка, что закладка сохранена в MongoDB."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/bookmarks',
            params={'film_id': str(film_id)},
            headers=auth_headers,
        )

        # MongoDB хранит film_id как Binary (UUID)
        bookmark = await mongo_client['bookmarks'].find_one({'film_id': _encode_uuid(film_id)})
        assert bookmark is not None
        assert 'user_id' in bookmark


# ==================================================================== #
#  Тесты лайков                                                          #
# ==================================================================== #


class TestLikesE2E:
    """E2E тесты для лайков."""

    async def test_add_like(self, aiohttp_session, clean_collections, auth_headers):
        """Добавление лайка."""
        film_id = uuid4()
        rating = 8

        async with aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/likes',
            params={'film_id': str(film_id), 'rating': rating},
            headers=auth_headers,
        ) as resp:
            assert resp.status == 201, f"Expected 201, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert 'film_id' in data
            assert data['film_id'] == str(film_id)
            assert data['rating'] == rating

    async def test_get_like_stats(self, aiohttp_session, clean_collections, auth_headers):
        """Получение статистики лайков."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/likes',
            params={'film_id': str(film_id), 'rating': 8},
            headers=auth_headers,
        )

        async with aiohttp_session.get(
            f'{UGC_BASE_URL}/api/v1/likes/{film_id}',
        ) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert 'total_ratings' in data
            assert data['total_ratings'] >= 1

    async def test_remove_like(self, aiohttp_session, clean_collections, auth_headers):
        """Удаление лайка."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/likes',
            params={'film_id': str(film_id), 'rating': 8},
            headers=auth_headers,
        )

        async with aiohttp_session.delete(
            f'{UGC_BASE_URL}/api/v1/likes/{film_id}',
            headers=auth_headers,
        ) as resp:
            assert resp.status == 204

    async def test_like_exists_in_mongodb(self, aiohttp_session, clean_collections, mongo_client, auth_headers):
        """Проверка, что лайк сохранён в MongoDB."""
        film_id = uuid4()
        rating = 9

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/likes',
            params={'film_id': str(film_id), 'rating': rating},
            headers=auth_headers,
        )

        like = await mongo_client['likes'].find_one({'film_id': _encode_uuid(film_id)})
        assert like is not None
        assert like['rating'] == rating


# ==================================================================== #
#  Тесты рецензий                                                        #
# ==================================================================== #


class TestReviewsE2E:
    """E2E тесты для рецензий."""

    async def test_create_review(self, aiohttp_session, clean_collections, auth_headers):
        """Создание рецензии."""
        film_id = uuid4()
        title = 'Отличный фильм'
        text = 'Прекрасная история'
        rating = 9

        async with aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': title,
                'text': text,
                'rating': rating,
            },
            headers=auth_headers,
        ) as resp:
            assert resp.status == 201, f"Expected 201, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert 'id' in data
            assert data['title'] == title
            assert data['rating'] == rating

    async def test_get_reviews(self, aiohttp_session, clean_collections, auth_headers):
        """Получение списка рецензий."""
        film_id = uuid4()

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': 'Тестовая рецензия',
                'text': 'Текст рецензии',
                'rating': 8,
            },
            headers=auth_headers,
        )

        async with aiohttp_session.get(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={'film_id': str(film_id)},
        ) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    async def test_get_review_detail(self, aiohttp_session, clean_collections, auth_headers):
        """Получение деталей рецензии."""
        film_id = uuid4()

        create_resp = await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': 'Детали рецензии',
                'text': 'Подробный текст',
                'rating': 10,
            },
            headers=auth_headers,
        )
        create_data = await create_resp.json()
        review_id = create_data['id']

        async with aiohttp_session.get(
            f'{UGC_BASE_URL}/api/v1/reviews/{review_id}',
        ) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert data['id'] == review_id
            assert data['text'] == 'Подробный текст'

    async def test_vote_on_review(self, aiohttp_session, clean_collections, auth_headers):
        """Голосование за рецензию."""
        film_id = uuid4()

        create_resp = await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': 'Рецензия для голосования',
                'text': 'Текст',
                'rating': 7,
            },
            headers=auth_headers,
        )
        create_data = await create_resp.json()
        review_id = create_data['id']

        async with aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews/{review_id}/vote',
            params={'is_like': 'true'},
            headers=auth_headers,
        ) as resp:
            assert resp.status == 200, f"Expected 200, got {resp.status}: {await resp.text()}"
            data = await resp.json()
            assert data['is_like'] is True
            assert data['review_id'] == review_id

    async def test_review_exists_in_mongodb(self, aiohttp_session, clean_collections, mongo_client, auth_headers):
        """Проверка, что рецензия сохранена в MongoDB."""
        film_id = uuid4()
        title = 'Проверка MongoDB'

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': title,
                'text': 'Текст для проверки',
                'rating': 8,
            },
            headers=auth_headers,
        )

        review = await mongo_client['reviews'].find_one({'film_id': _encode_uuid(film_id)})
        assert review is not None
        assert review['title'] == title

    async def test_vote_exists_in_mongodb(self, aiohttp_session, clean_collections, mongo_client, auth_headers):
        """Проверка, что голос сохранён в MongoDB."""
        film_id = uuid4()

        create_resp = await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews',
            params={
                'film_id': str(film_id),
                'title': 'Рецензия для проверки голоса',
                'text': 'Текст',
                'rating': 9,
            },
            headers=auth_headers,
        )
        create_data = await create_resp.json()
        review_id = create_data['id']

        await aiohttp_session.post(
            f'{UGC_BASE_URL}/api/v1/reviews/{review_id}/vote',
            params={'is_like': 'true'},
            headers=auth_headers,
        )

        # Ищем голос по review_id (ObjectId string → ObjectId)
        vote = await mongo_client['review_votes'].find_one({'review_id': _to_objectid(review_id)})
        assert vote is not None
        assert vote['is_like'] is True
