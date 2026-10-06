"""Тесты для сервиса работы с лайками (like_service)."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

from services.like_service import (
    add_or_update_like,
    get_film_like_stats,
    invalidate_film_stats_cache,
    remove_like,
)


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def film_id():
    return uuid.uuid4()


@pytest.fixture
def mock_redis_client():
    """Фикстура для мока Redis-клиента."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.setex = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def mock_get_redis(mock_redis_client):
    """Патч функции получения Redis-клиента."""
    with patch("services.like_service.get_redis", return_value=mock_redis_client) as mock:
        yield mock


@pytest.fixture
def mock_like_collection():
    """Фикстура для мока MongoDB коллекции через Beanie."""
    collection = AsyncMock()
    collection.aggregate = MagicMock()
    
    # Настраиваем цепочку вызовов: collection.aggregate(...).to_list(length=1)
    mock_cursor = AsyncMock()
    mock_cursor.to_list = AsyncMock()
    collection.aggregate.return_value = mock_cursor
    
    with patch("models.like.Like.get_motor_collection", return_value=collection):
        yield collection, mock_cursor


# ==============================================================================
# Тесты get_film_like_stats (Кэширование)
# ==============================================================================

@pytest.mark.asyncio
async def test_get_film_like_stats_cache_hit(mock_get_redis, mock_redis_client, mock_like_collection, film_id):
    """Если данные есть в Redis, MongoDB не опрашивается."""
    cached_data = {
        "film_id": str(film_id),
        "total_likes": 5,
        "total_dislikes": 1,
        "average_rating": 7.5,
        "total_ratings": 10,
        "rating_distribution": {str(i): 1 for i in range(11)},
    }
    mock_redis_client.get.return_value = json.dumps(cached_data)
    collection, mock_cursor = mock_like_collection

    result = await get_film_like_stats(film_id)

    # Проверяем, что читали из Redis
    mock_redis_client.get.assert_awaited_once()
    # Проверяем, что в MongoDB НЕ обращались
    mock_cursor.to_list.assert_not_awaited()
    # Проверяем, что вернули корректные данные
    assert result == cached_data


@pytest.mark.asyncio
async def test_get_film_like_stats_cache_miss(mock_get_redis, mock_redis_client, mock_like_collection, film_id):
    """Если данных нет в Redis, выполняется запрос к MongoDB и результат сохраняется в Redis."""
    mock_redis_client.get.return_value = None  # Cache miss
    
    # Мокаем ответ MongoDB ($facet)
    collection, mock_cursor = mock_like_collection
    mock_cursor.to_list.return_value = [
        {
            "summary": [
                {
                    "total_ratings": 2,
                    "rating_sum": 15,
                    "total_likes": 1,
                    "total_dislikes": 0,
                    "average_rating": 7.5,
                }
            ],
            "distribution": [{"_id": 7, "count": 1}, {"_id": 8, "count": 1}],
        }
    ]

    result = await get_film_like_stats(film_id)

    # Проверяем, что обратились к MongoDB
    mock_cursor.to_list.assert_awaited_once_with(length=1)
    
    # Проверяем, что сохранили в Redis с правильным TTL (по умолчанию 60)
    expected_stats = {
        "film_id": str(film_id),
        "total_likes": 1,
        "total_dislikes": 0,
        "average_rating": 7.5,
        "total_ratings": 2,
        # Используем строковые ключи, так как json.loads вернёт именно их
        "rating_distribution": {str(i): 0 for i in range(11)} | {"7": 1, "8": 1},
    }

    mock_redis_client.setex.assert_awaited_once()
    call_args = mock_redis_client.setex.call_args
    assert call_args[0][0] == f"film_stats:{film_id}"
    assert call_args[0][1] == 60  # TTL из settings
    assert json.loads(call_args[0][2]) == expected_stats
    
    assert result == expected_stats


@pytest.mark.asyncio
async def test_get_film_like_stats_redis_read_fails_fallback_to_mongo(
    mock_get_redis, mock_redis_client, mock_like_collection, film_id
):
    """Если Redis падает при чтении, сервис корректно падает до MongoDB (graceful degradation)."""
    mock_redis_client.get.side_effect = RedisError("Connection lost")
    
    collection, mock_cursor = mock_like_collection
    mock_cursor.to_list.return_value = [
        {"summary": [{"total_ratings": 1, "rating_sum": 10, "total_likes": 1, "total_dislikes": 0, "average_rating": 10.0}], "distribution": []}
    ]

    result = await get_film_like_stats(film_id)

    # Упали до Mongo
    mock_cursor.to_list.assert_awaited_once()
    # Вернули корректный результат, несмотря на ошибку Redis
    assert result["total_ratings"] == 1
    assert result["average_rating"] == 10.0


# ==============================================================================
# Тесты инвалидации кэша при записи/удалении
# ==============================================================================

@pytest.mark.asyncio
async def test_add_or_update_like_invalidates_cache(mock_get_redis, mock_redis_client, film_id, user_id):
    """При создании или обновлении лайка кэш для этого фильма должен быть инвалидирован."""
    # Мокаем успешное создание
    mock_like_instance = AsyncMock()
    mock_like_instance.insert = AsyncMock()
    
    with patch("services.like_service.Like", return_value=mock_like_instance):
        await add_or_update_like(user_id=user_id, film_id=film_id, rating=8)

    # Проверяем, что вызвали delete в Redis для инвалидации
    mock_redis_client.delete.assert_awaited_once_with(f"film_stats:{film_id}")


@pytest.mark.asyncio
async def test_remove_like_invalidates_cache(mock_get_redis, mock_redis_client, film_id, user_id):
    """При удалении лайка кэш для этого фильма должен быть инвалидирован."""
    # Мокаем поиск и удаление лайка
    mock_like_instance = AsyncMock()
    mock_like_instance.delete = AsyncMock()
    
    with patch("services.like_service.Like.get", return_value=mock_like_instance):
        result = await remove_like(user_id=user_id, film_id=film_id)

    assert result is True
    mock_like_instance.delete.assert_awaited_once()
    # Проверяем, что вызвали delete в Redis для инвалидации
    mock_redis_client.delete.assert_awaited_once_with(f"film_stats:{film_id}")


@pytest.mark.asyncio
async def test_invalidate_cache_redis_error_does_not_crash(mock_get_redis, mock_redis_client, film_id):
    """Ошибка Redis при инвалидации не должна ронять весь сервис (логирование предупреждения)."""
    mock_redis_client.delete.side_effect = RedisError("Redis is down")

    # Функция должна выполниться без выброса исключения
    await invalidate_film_stats_cache(film_id)
    
    mock_redis_client.delete.assert_awaited_once_with(f"film_stats:{film_id}")