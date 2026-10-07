"""Сервис работы с лайками."""

import json
import logging
from datetime import datetime
from uuid import UUID

from redis.exceptions import RedisError
from models.like import Like, like_id
from pymongo.errors import DuplicateKeyError

from core.redis_client import get_redis
from config import settings

logger = logging.getLogger(__name__)

# Префикс ключа кэша
_FILM_STATS_KEY = "film_stats:{film_id}"


def _cache_key(film_id: UUID) -> str:
    return _FILM_STATS_KEY.format(film_id=str(film_id))


async def add_or_update_like(
    user_id: UUID,
    film_id: UUID,
    rating: int,
) -> Like:
    """Добавить или обновить лайк (оценка 0-10)."""
    like = Like(
        id=like_id(user_id, film_id),
        user_id=user_id,
        film_id=film_id,
        rating=rating,
    )
    try:
        await like.insert()
        logger.info('Лайк создан: user=%s film=%s rating=%d', user_id, film_id, rating)
    except DuplicateKeyError:
        # Оценка уже есть (в т.ч. гонка параллельных запросов) — обновляем.
        existing = await Like.get(like_id(user_id, film_id))
        if existing:
            existing.rating = rating
            existing.updated_at = datetime.utcnow()
            await existing.save()
            logger.info('Лайк обновлён: user=%s film=%s rating=%d', user_id, film_id, rating)
            like = existing

    # ✅ ИНВАЛИДАЦИЯ КЭША при записи (Write-Invalidate)
    await invalidate_film_stats_cache(film_id)
    
    return like


async def remove_like(user_id: UUID, film_id: UUID) -> bool:
    """Удалить лайк."""
    like = await Like.get(like_id(user_id, film_id))
    if like:
        await like.delete()
        logger.info('Лайк удалён: user=%s film=%s', user_id, film_id)
        
        # ✅ ИНВАЛИДАЦИЯ КЭША при удалении
        await invalidate_film_stats_cache(film_id)
        return True
    return False


async def get_film_like_stats(film_id: UUID) -> dict:
    """
    Получить статистику лайков для фильма.
    1. Пытаемся прочитать из Redis (Cache-Aside).
    2. На miss — выполняем $facet-агрегацию в Mongo и кладём в Redis.
    3. На сбой Redis — fallback на Mongo (graceful degradation).
    """
    cache_key = _cache_key(film_id)

    # --- 1. Читаем из кэша ---
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except RedisError as e:
        logger.warning("redis_read_failed", extra={"film_id": str(film_id), "error": str(e)})
    except Exception:
        logger.exception("redis_unexpected_error", extra={"film_id": str(film_id)})

    # --- 2. Cache miss: тяжёлая агрегация в Mongo ---
    pipeline = [
        {"$match": {"film_id": film_id}},
        {
            "$facet": {
                "summary": [
                    {
                        "$group": {
                            "_id": None,
                            "total_ratings": {"$sum": 1},
                            "rating_sum": {"$sum": "$rating"},
                            "total_likes": {
                                "$sum": {"$cond": [{"$gt": ["$rating", 5]}, 1, 0]}
                            },
                            "total_dislikes": {
                                "$sum": {"$cond": [{"$lt": ["$rating", 3]}, 1, 0]}
                            },
                        }
                    },
                    {
                        "$project": {
                            "_id": 0,
                            "total_ratings": 1,
                            "rating_sum": 1,
                            "total_likes": 1,
                            "total_dislikes": 1,
                            "average_rating": {
                                "$round": [
                                    {
                                        "$cond": [
                                            {"$eq": ["$total_ratings", 0]},
                                            0,
                                            {"$divide": ["$rating_sum", "$total_ratings"]},
                                        ]
                                    },
                                    2,
                                ]
                            },
                        }
                    },
                ],
                "distribution": [
                    {"$group": {"_id": "$rating", "count": {"$sum": 1}}},
                    {"$sort": {"_id": 1}},
                ],
            }
        },
    ]

    result = await Like.get_motor_collection().aggregate(pipeline).to_list(length=1)
    doc = result[0] if result else None

    summary = doc.get("summary", [{}]) if doc else [{}]
    summary = summary[0] if summary else {}

    # ✅ ИСПРАВЛЕНИЕ: Используем строковые ключи для корректной JSON-сериализации
    distribution: dict[str, int] = {str(i): 0 for i in range(11)}
    if doc and doc.get("distribution"):
        for item in doc["distribution"]:
            distribution[str(item["_id"])] = item["count"]

    stats = {
        'film_id': str(film_id),
        'total_likes': summary.get('total_likes', 0),
        'total_dislikes': summary.get('total_dislikes', 0),
        'average_rating': summary.get('average_rating', 0.0),
        'total_ratings': summary.get('total_ratings', 0),
        'rating_distribution': distribution,
    }

    # --- 3. Пишем в кэш (best-effort) ---
    try:
        redis = await get_redis()
        await redis.setex(
            cache_key,
            settings.film_stats_cache_ttl,
            json.dumps(stats),
        )
    except RedisError as e:
        logger.warning("redis_write_failed", extra={"film_id": str(film_id), "error": str(e)})

    return stats


async def invalidate_film_stats_cache(film_id: UUID) -> None:
    """Сбросить кэш статистики фильма (вызывается при записи/удалении)."""
    cache_key = _cache_key(film_id)
    try:
        redis = await get_redis()
        await redis.delete(cache_key)
    except RedisError as e:
        # Не критично: кэш протухнет по TTL через 60 сек
        logger.warning("cache_invalidation_failed", extra={"film_id": str(film_id), "error": str(e)})


async def get_user_likes(
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> list[Like]:
    """Получить оценки, выставленные пользователем (для агрегирующей витрины профиля, S11_T6)."""
    return (
        await Like.find(Like.user_id == user_id)
        .sort([('updated_at', -1)])
        .skip(skip)
        .limit(limit)
        .to_list()
    )