"""Тесты для shared/ugc_schemas.py."""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.ugc_schemas import (
    BookmarkSchema,
    LikeSchema,
    LikeStatsSchema,
    ReviewSchema,
    ReviewVoteSchema,
    ReviewWithAuthorSchema,
)


class TestBookmarkSchema:
    """Тесты модели BookmarkSchema."""

    def test_create_bookmark(self):
        film_id = uuid4()
        bookmark = BookmarkSchema(
            film_id=film_id,
            film_title='Test Film',
            added_at=datetime.utcnow(),
        )
        assert bookmark.film_id == film_id
        assert bookmark.film_title == 'Test Film'
        assert bookmark.film_poster is None

    def test_bookmark_with_poster(self):
        bookmark = BookmarkSchema(
            film_id=uuid4(),
            film_title='Test',
            film_poster='http://example.com/poster.jpg',
            added_at=datetime.utcnow(),
        )
        assert bookmark.film_poster == 'http://example.com/poster.jpg'


class TestLikeSchema:
    """Тесты модели LikeSchema."""

    def test_create_like(self):
        like = LikeSchema(
            user_id=uuid4(),
            film_id=uuid4(),
            rating=8,
            created_at=datetime.utcnow(),
        )
        assert like.rating == 8

    def test_like_rating_bounds(self):
        # Минимальный рейтинг
        like = LikeSchema(
            user_id=uuid4(), film_id=uuid4(), rating=0, created_at=datetime.utcnow()
        )
        assert like.rating == 0

        # Максимальный рейтинг
        like = LikeSchema(
            user_id=uuid4(), film_id=uuid4(), rating=10, created_at=datetime.utcnow()
        )
        assert like.rating == 10

    def test_like_rating_invalid(self):
        with pytest.raises(ValidationError):
            LikeSchema(
                user_id=uuid4(), film_id=uuid4(), rating=11, created_at=datetime.utcnow()
            )

        with pytest.raises(ValidationError):
            LikeSchema(
                user_id=uuid4(), film_id=uuid4(), rating=-1, created_at=datetime.utcnow()
            )


class TestLikeStatsSchema:
    """Тесты модели LikeStatsSchema."""

    def test_default_stats(self):
        stats = LikeStatsSchema(film_id=uuid4())
        assert stats.total_likes == 0
        assert stats.total_dislikes == 0
        assert stats.average_rating == 0.0

    def test_stats_with_data(self):
        stats = LikeStatsSchema(
            film_id=uuid4(),
            total_likes=100,
            total_dislikes=20,
            average_rating=7.5,
            total_ratings=150,
            rating_distribution={5: 50, 6: 30, 7: 40, 8: 30},
        )
        assert stats.total_likes == 100
        assert stats.total_dislikes == 20
        assert stats.average_rating == 7.5


class TestReviewSchema:
    """Тесты модели ReviewSchema."""

    def test_create_review(self):
        review = ReviewSchema(
            id=uuid4(),
            user_id=uuid4(),
            user_name='Test User',
            film_id=uuid4(),
            title='Great Film',
            text='I loved it!',
            rating=9,
            published_at=datetime.utcnow(),
            likes_count=10,
            dislikes_count=1,
        )
        assert review.title == 'Great Film'
        assert review.rating == 9
        assert review.likes_count == 10

    def test_review_rating_bounds(self):
        review = ReviewSchema(
            id=uuid4(),
            user_id=uuid4(),
            user_name='Test',
            film_id=uuid4(),
            title='Test',
            text='Test',
            rating=0,
            published_at=datetime.utcnow(),
        )
        assert review.rating == 0

        review = ReviewSchema(
            id=uuid4(),
            user_id=uuid4(),
            user_name='Test',
            film_id=uuid4(),
            title='Test',
            text='Test',
            rating=10,
            published_at=datetime.utcnow(),
        )
        assert review.rating == 10

    def test_review_rating_invalid(self):
        with pytest.raises(ValidationError):
            ReviewSchema(
                id=uuid4(),
                user_id=uuid4(),
                user_name='Test',
                film_id=uuid4(),
                title='Test',
                text='Test',
                rating=11,
                published_at=datetime.utcnow(),
            )


class TestReviewVoteSchema:
    """Тесты модели ReviewVoteSchema."""

    def test_like_vote(self):
        vote = ReviewVoteSchema(
            review_id=uuid4(), is_like=True, voted_at=datetime.utcnow()
        )
        assert vote.is_like is True

    def test_dislike_vote(self):
        vote = ReviewVoteSchema(
            review_id=uuid4(), is_like=False, voted_at=datetime.utcnow()
        )
        assert vote.is_like is False


class TestReviewWithAuthorSchema:
    """Тесты модели ReviewWithAuthorSchema."""

    def test_with_avatar(self):
        review = ReviewWithAuthorSchema(
            id=uuid4(),
            user_id=uuid4(),
            user_name='Test',
            film_id=uuid4(),
            title='Test',
            text='Test',
            rating=5,
            published_at=datetime.utcnow(),
            author_avatar='http://example.com/avatar.jpg',
        )
        assert review.author_avatar == 'http://example.com/avatar.jpg'

    def test_without_avatar(self):
        review = ReviewWithAuthorSchema(
            id=uuid4(),
            user_id=uuid4(),
            user_name='Test',
            film_id=uuid4(),
            title='Test',
            text='Test',
            rating=5,
            published_at=datetime.utcnow(),
        )
        assert review.author_avatar is None
