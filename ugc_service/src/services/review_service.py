"""Сервис работы с рецензиями."""

import logging
from uuid import UUID

from bson import ObjectId
from models.review import Review, ReviewVote

logger = logging.getLogger(__name__)


async def create_review(
    user_id: UUID,
    film_id: UUID,
    title: str,
    text: str,
    rating: int,
) -> Review:
    """Создать рецензию."""
    review = Review(
        user_id=user_id,
        film_id=film_id,
        title=title,
        text=text,
        rating=rating,
    )
    await review.insert()
    logger.info('Рецензия создана: user=%s film=%s', user_id, film_id)
    return review


async def get_film_reviews(
    film_id: UUID,
    sort_by: str = 'likes_count',
    skip: int = 0,
    limit: int = 20,
) -> list[Review]:
    """Получить список рецензий к фильму с сортировкой."""
    sort_map = {
        'likes_count': [('likes_count', -1)],
        'published_at': [('published_at', -1)],
        'rating': [('rating', -1)],
    }
    sort_field = sort_map.get(sort_by, [('likes_count', -1)])

    reviews = await Review.find(
        Review.film_id == film_id,
    ).sort(*sort_field).skip(skip).limit(limit).to_list()
    return reviews


async def get_review_by_id(review_id: ObjectId) -> Review | None:
    """Получить рецензию по ID."""
    return await Review.get(review_id)


async def update_review(
    review_id: ObjectId,
    user_id: UUID,
    title: str | None = None,
    text: str | None = None,
    rating: int | None = None,
) -> Review | None:
    """Обновить рецензию (только автор)."""
    review = await Review.get(review_id)
    if not review or review.user_id != user_id:
        return None

    if title is not None:
        review.title = title
    if text is not None:
        review.text = text
    if rating is not None:
        review.rating = rating

    await review.save()
    logger.info('Рецензия обновлена: %s', review_id)
    return review


async def delete_review(review_id: ObjectId, user_id: UUID) -> bool:
    """Удалить рецензию (только автор)."""
    review = await Review.get(review_id)
    if not review or review.user_id != user_id:
        return False

    await review.delete()
    # Удаляем связанные голоса
    await ReviewVote.find(ReviewVote.review_id == review_id).delete()
    logger.info('Рецензия удалена: %s', review_id)
    return True


async def vote_on_review(
    user_id: UUID,
    review_id: ObjectId,
    is_like: bool,
) -> ReviewVote:
    """Проголосовать за/против рецензии."""
    existing = await ReviewVote.find_one(
        ReviewVote.user_id == user_id,
        ReviewVote.review_id == review_id,
    )

    if existing:
        # Обновляем голос
        old_is_like = existing.is_like
        existing.is_like = is_like
        await existing.save()

        # Обновляем счётчики
        review = await Review.get(review_id)
        if review:
            if old_is_like != is_like:
                if old_is_like:
                    review.likes_count -= 1
                    review.dislikes_count += 1
                else:
                    review.dislikes_count -= 1
                    review.likes_count += 1
                await review.save()
        return existing

    # Новый голос
    vote = ReviewVote(user_id=user_id, review_id=review_id, is_like=is_like)
    await vote.insert()

    # Обновляем счётчики
    review = await Review.get(review_id)
    if review:
        if is_like:
            review.likes_count += 1
        else:
            review.dislikes_count += 1
        await review.save()

    logger.info('Голос добавлен: user=%s review=%s like=%s', user_id, review_id, is_like)
    return vote


async def remove_vote(user_id: UUID, review_id: UUID) -> bool:
    """Удалить голос."""
    vote = await ReviewVote.find_one(
        ReviewVote.user_id == user_id,
        ReviewVote.review_id == review_id,
    )
    if not vote:
        return False

    # Обновляем счётчики
    review = await Review.get(review_id)
    if review:
        if vote.is_like:
            review.likes_count -= 1
        else:
            review.dislikes_count -= 1
        await review.save()

    await vote.delete()
    logger.info('Голос удалён: user=%s review=%s', user_id, review_id)
    return True
