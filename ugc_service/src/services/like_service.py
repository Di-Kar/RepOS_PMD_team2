"""Сервис работы с лайками."""

import logging
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
        existing.updated_at = existing.updated_at.__class__.utcnow()
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
    """Получить статистику лайков для фильма."""
    all_likes = await Like.find(
        Like.film_id == film_id,
    ).to_list()

    total_ratings = len(all_likes)
    total_likes = 0  # rating > 5
    total_dislikes = 0  # rating < 3
    rating_sum = 0
    distribution = dict.fromkeys(range(11), 0)

    for like in all_likes:
        r = like.rating
        distribution[r] = distribution.get(r, 0) + 1
        rating_sum += r
        if r > 5:
            total_likes += 1
        elif r < 3:
            total_dislikes += 1

    average_rating = round(rating_sum / total_ratings, 2) if total_ratings > 0 else 0.0

    return {
        'film_id': str(film_id),
        'total_likes': total_likes,
        'total_dislikes': total_dislikes,
        'average_rating': average_rating,
        'total_ratings': total_ratings,
        'rating_distribution': distribution,
    }
