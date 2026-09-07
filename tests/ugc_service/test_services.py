"""Тесты сервисов ugc_service (без MongoDB)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestBookmarkService:
    """Тесты bookmark_service."""

    async def test_add_bookmark(self, mock_beanie):
        """Создание закладки."""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.insert = AsyncMock()

        with patch('services.bookmark_service.Bookmark') as MockBookmark:
            MockBookmark.get = AsyncMock(return_value=None)
            MockBookmark.return_value = mock_instance

            from services.bookmark_service import add_bookmark

            user_id = uuid4()
            film_id = uuid4()
            result = await add_bookmark(user_id, film_id)

            assert result is mock_instance
            MockBookmark.assert_called_once_with(
                id=f'{user_id}:{film_id}', user_id=user_id, film_id=film_id
            )
            mock_instance.insert.assert_called_once()

    async def test_remove_bookmark(self, mock_beanie):
        """Удаление закладки."""
        mock_instance = MagicMock()
        mock_instance.delete = AsyncMock()

        with patch('services.bookmark_service.Bookmark') as MockBookmark:
            MockBookmark.get = AsyncMock(return_value=mock_instance)

            from services.bookmark_service import remove_bookmark

            user_id = uuid4()
            film_id = uuid4()
            result = await remove_bookmark(user_id, film_id)

            assert result is True
            mock_instance.delete.assert_called_once()

    async def test_remove_bookmark_not_found(self, mock_beanie):
        """Удаление несуществующей закладки."""
        with patch('services.bookmark_service.Bookmark') as MockBookmark:
            MockBookmark.get = AsyncMock(return_value=None)

            from services.bookmark_service import remove_bookmark

            user_id = uuid4()
            film_id = uuid4()
            result = await remove_bookmark(user_id, film_id)

            assert result is False

    async def test_get_user_bookmarks(self, mock_beanie):
        """Получение списка закладок."""
        mock_bookmark = MagicMock()
        mock_bookmark.film_id = uuid4()
        mock_bookmark.created_at = MagicMock()

        mock_query = MagicMock()
        mock_query.to_list = AsyncMock(return_value=[mock_bookmark])

        with patch('services.bookmark_service.Bookmark') as MockBookmark:
            MockBookmark.find = MagicMock(return_value=mock_query)

            from services.bookmark_service import get_user_bookmarks

            user_id = uuid4()
            result = await get_user_bookmarks(user_id)

            assert len(result) == 1
            assert result[0].film_id == mock_bookmark.film_id


class TestLikeService:
    """Тесты like_service."""

    async def test_add_or_update_like_new(self, mock_beanie):
        """Создание нового лайка."""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.insert = AsyncMock()

        with patch('services.like_service.Like') as MockLike:
            MockLike.get = AsyncMock(return_value=None)
            MockLike.return_value = mock_instance

            from services.like_service import add_or_update_like

            user_id = uuid4()
            film_id = uuid4()
            result = await add_or_update_like(user_id, film_id, 8)

            assert result is mock_instance

    async def test_add_or_update_like_existing(self, mock_beanie):
        """Обновление существующего лайка."""
        from pymongo.errors import DuplicateKeyError

        mock_instance = MagicMock()
        mock_instance.save = AsyncMock()

        with patch('services.like_service.Like') as MockLike:
            # insert() бросает DuplicateKeyError, поэтому find_one вызывается
            mock_instance.insert = AsyncMock(side_effect=DuplicateKeyError('dup'))
            MockLike.return_value = mock_instance
            MockLike.get = AsyncMock(return_value=mock_instance)

            from services.like_service import add_or_update_like

            user_id = uuid4()
            film_id = uuid4()
            result = await add_or_update_like(user_id, film_id, 9)

            assert result is mock_instance
            mock_instance.save.assert_called_once()

    async def test_get_film_like_stats(self, mock_beanie):
        """Получение статистики лайков."""
        mock_aggregation_cursor = AsyncMock()
        mock_aggregation_cursor.to_list = AsyncMock(
            return_value=[{
                'summary': [{'total_ratings': 2, 'total_likes': 1, 'total_dislikes': 1, 'average_rating': 5.0}],
                'distribution': [{'_id': 8, 'count': 1}, {'_id': 2, 'count': 1}],
            }]
        )

        with patch('services.like_service.Like') as MockLike:
            MockLike.get_motor_collection.return_value.aggregate.return_value = mock_aggregation_cursor

            from services.like_service import get_film_like_stats

            film_id = uuid4()
            result = await get_film_like_stats(film_id)

            assert result['total_ratings'] == 2
            assert result['total_likes'] == 1
            assert result['total_dislikes'] == 1


class TestReviewService:
    """Тесты review_service."""

    async def test_create_review(self, mock_beanie):
        """Создание рецензии."""
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_instance.insert = AsyncMock()

        with patch('services.review_service.Review') as MockReview:
            MockReview.return_value = mock_instance

            from services.review_service import create_review

            user_id = uuid4()
            film_id = uuid4()
            result = await create_review(user_id, film_id, 'Title', 'Text', 8)

            assert result is mock_instance
            mock_instance.insert.assert_called_once()

    @patch('services.review_service.ReviewVote')
    async def test_vote_on_review(self, mock_vote_cls, mock_beanie):
        """Голосование за рецензию."""
        mock_review = MagicMock()
        mock_review.save = AsyncMock()

        mock_vote = MagicMock()
        mock_vote.id = uuid4()
        mock_vote.insert = AsyncMock()

        with patch('services.review_service.Review') as MockReview:
            MockReview.get = AsyncMock(return_value=mock_review)

            mock_vote_cls.get = AsyncMock(return_value=None)
            mock_vote_cls.return_value = mock_vote

            from services.review_service import vote_on_review

            user_id = uuid4()
            review_id = uuid4()
            result = await vote_on_review(user_id, review_id, True)

            assert result is mock_vote
            mock_vote.insert.assert_called_once()

    async def test_vote_on_review_not_found(self, mock_beanie):
        """Голосование за несуществующую рецензию → ValueError."""
        with patch('services.review_service.Review') as MockReview:
            MockReview.get = AsyncMock(return_value=None)

            from services.review_service import vote_on_review

            user_id = uuid4()
            review_id = uuid4()

            with pytest.raises(ValueError, match='not found'):
                await vote_on_review(user_id, review_id, True)

    @patch('services.review_service.ReviewVote')
    async def test_delete_review(self, mock_vote_cls, mock_beanie):
        """Удаление рецензии."""
        mock_review = MagicMock()
        mock_review.user_id = uuid4()
        mock_review.delete = AsyncMock()

        mock_vote_query = MagicMock()
        mock_vote_query.delete = AsyncMock()

        with patch('services.review_service.Review') as MockReview:
            MockReview.get = AsyncMock(return_value=mock_review)
            mock_vote_cls.find = MagicMock(return_value=mock_vote_query)

            from services.review_service import delete_review

            review_id = uuid4()
            user_id = mock_review.user_id
            result = await delete_review(review_id, user_id)

            assert result is True
            mock_review.delete.assert_called_once()
            mock_vote_query.delete.assert_called_once()

    async def test_delete_review_not_owner(self, mock_beanie):
        """Удаление рецензии не владельцем."""
        mock_review = MagicMock()
        mock_review.user_id = uuid4()  # другой пользователь

        with patch('services.review_service.Review') as MockReview:
            MockReview.get = AsyncMock(return_value=mock_review)

            from services.review_service import delete_review

            review_id = uuid4()
            other_user = uuid4()
            result = await delete_review(review_id, other_user)

            assert result is False
