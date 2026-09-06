"""Сервис работы с лайками."""

import logging
from datetime import datetime
from uuid import UUID

from models.like import Like

logger = logging.getLogger(__name__)


async def add_or_update_like(
    user_id: UUID,
    film_id: UUID,
    rating: int,
) -> Like:
    """Добавить или обновить лайк (оценка 0-10)."""
    existing = await Like.find_one(
        Like.user_id == user_id,
        Like.film_id == film_id,
    )
    if existing:
        existing.rating = rating
        existing.updated_at = datetime.utcnow()
        await existing.save()
        logger.info(
            'Лайк обновлён: user=%s film=%s rating=%d', user_id, film_id, rating
        )
        return existing

    like = Like(user_id=user_id, film_id=film_id, rating=rating)
    await like.insert()
    logger.info('Лайк создан: user=%s film=%s rating=%d', user_id, film_id, rating)
    return like


async def remove_like(user_id: UUID, film_id: UUID) -> bool:
    """Удалить лайк."""
    like = await Like.find_one(
        Like.user_id == user_id,
        Like.film_id == film_id,
    )
    if like:
        await like.delete()
        logger.info('Лайк удалён: user=%s film=%s', user_id, film_id)
        return True
    return False


async def get_film_like_stats(film_id: UUID) -> dict:
    """Получить статистику лайков для фильма (aggregation pipeline).

    Использует MongoDB $facet для расчёта метрик и распределения
    на стороне базы данных — в память попадает один документ с результатами.
    """
    pipeline = [
        # Фильтрация по фильму
        {"$match": {"film_id": film_id}},

        # Параллельный расчёт метрик и распределения
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
                                            {"$divide": ["$rating_sum", "$total_ratings"]}
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

    result = await Like.collection.aggregate(pipeline).to_list(length=1)
    doc = result[0] if result else None

    summary = doc.get("summary", [{}])[0] if doc else {}

    # Распределение: словарь {0: count, 1: count, ..., 10: count}
    distribution: dict[int, int] = dict.fromkeys(range(11), 0)
    if doc and doc.get("distribution"):
        for item in doc["distribution"]:
            distribution[item["_id"]] = item["count"]

    return {
        'film_id': str(film_id),
        'total_likes': summary.get('total_likes', 0),
        'total_dislikes': summary.get('total_dislikes', 0),
        'average_rating': summary.get('average_rating', 0.0),
        'total_ratings': summary.get('total_ratings', 0),
        'rating_distribution': distribution,
    }
