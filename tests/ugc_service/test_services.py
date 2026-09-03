"""Тесты сервисов ugc_service (без MongoDB)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestBookmarkService:
    """Тесты bookmark_service."""

    @patch('services.bookmark_service.Bookmark')
    async def test_add_bookmark(self, mock_bookmark_cls, mock_beanie):
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_bookmark_cls.find_one = AsyncMock(return_value=None)
        mock_bookmark_cls.return_value = mock_instance
        mock_instance.insert = AsyncMock()

        from services.bookmark_service import add_bookmark

        user_id = uuid4()
        film_id = uuid4()
        result = await add_bookmark(user_id, film_id)

        assert result is mock_instance
        mock_bookmark_cls.find_one.assert_called_once()
        mock_bookmark_cls.return_value.insert.assert_called_once()

    @patch('services.bookmark_service.Bookmark')
    async def test_remove_bookmark(self, mock_bookmark_cls, mock_beanie):
        mock_instance = MagicMock()
        mock_instance.delete = AsyncMock()
        mock_bookmark_cls.find_one = AsyncMock(return_value=mock_instance)

        from services.bookmark_service import remove_bookmark

        user_id = uuid4()
        film_id = uuid4()
        result = await remove_bookmark(user_id, film_id)

        assert result is True
        mock_instance.delete.assert_called_once()

    @patch('services.bookmark_service.Bookmark')
    async def test_remove_bookmark_not_found(self, mock_bookmark_cls, mock_beanie):
        mock_bookmark_cls.find_one = AsyncMock(return_value=None)

        from services.bookmark_service import remove_bookmark

        user_id = uuid4()
        film_id = uuid4()
        result = await remove_bookmark(user_id, film_id)

        assert result is False

    @patch('services.bookmark_service.Bookmark')
    async def test_get_user_bookmarks(self, mock_bookmark_cls, mock_beanie):
        mock_bookmark = MagicMock()
        mock_bookmark.film_id = uuid4()
        mock_bookmark.created_at = MagicMock()
        mock_bookmark_cls.find = MagicMock()
        mock_query = MagicMock()
        mock_query.to_list = AsyncMock(return_value=[mock_bookmark])
        mock_bookmark_cls.find.return_value = mock_query

        from services.bookmark_service import get_user_bookmarks

        user_id = uuid4()
        result = await get_user_bookmarks(user_id)

        assert len(result) == 1
        assert result[0].film_id == mock_bookmark.film_id


class TestLikeService:
    """Тесты like_service."""

    @patch('services.like_service.Like')
    async def test_add_or_update_like_new(self, mock_like_cls, mock_beanie):
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_like_cls.find_one = AsyncMock(return_value=None)
        mock_like_cls.return_value = mock_instance
        mock_instance.insert = AsyncMock()

        from services.like_service import add_or_update_like

        user_id = uuid4()
        film_id = uuid4()
        result = await add_or_update_like(user_id, film_id, 8)

        assert result is mock_instance

    @patch('services.like_service.Like')
    async def test_add_or_update_like_existing(self, mock_like_cls, mock_beanie):
        mock_instance = MagicMock()
        mock_instance.save = AsyncMock()
        mock_like_cls.find_one = AsyncMock(return_value=mock_instance)

        from services.like_service import add_or_update_like

        user_id = uuid4()
        film_id = uuid4()
        result = await add_or_update_like(user_id, film_id, 9)

        assert result is mock_instance
        mock_instance.save.assert_called_once()

    @patch('services.like_service.Like')
    async def test_get_film_like_stats(self, mock_like_cls, mock_beanie):
        mock_like1 = MagicMock()
        mock_like1.rating = 8
        mock_like2 = MagicMock()
        mock_like2.rating = 2
        mock_like_cls.find = MagicMock()
        mock_query = MagicMock()
        mock_query.to_list = AsyncMock(return_value=[mock_like1, mock_like2])
        mock_like_cls.find.return_value = mock_query

        from services.like_service import get_film_like_stats

        film_id = uuid4()
        result = await get_film_like_stats(film_id)

        assert result['total_ratings'] == 2
        assert result['total_likes'] == 1
        assert result['total_dislikes'] == 1


class TestReviewService:
    """Тесты review_service."""

    @patch('services.review_service.Review')
    async def test_create_review(self, mock_review_cls, mock_beanie):
        mock_instance = MagicMock()
        mock_instance.id = uuid4()
        mock_review_cls.return_value = mock_instance
        mock_instance.insert = AsyncMock()

        from services.review_service import create_review

        user_id = uuid4()
        film_id = uuid4()
        result = await create_review(user_id, film_id, 'Title', 'Text', 8)

        assert result is mock_instance
        mock_instance.insert.assert_called_once()

    @patch('services.review_service.Review')
    @patch('services.review_service.ReviewVote')
    async def test_vote_on_review(self, mock_vote_cls, mock_review_cls, mock_beanie):
        mock_review = MagicMock()
        mock_review.save = AsyncMock()
        mock_review_cls.get = AsyncMock(return_value=mock_review)

        mock_vote = MagicMock()
        mock_vote.id = uuid4()
        mock_vote_cls.find_one = AsyncMock(return_value=None)
        mock_vote_cls.return_value = mock_vote
        mock_vote.insert = AsyncMock()

        from services.review_service import vote_on_review

        user_id = uuid4()
        review_id = uuid4()
        result = await vote_on_review(user_id, review_id, True)

        assert result is mock_vote
        mock_vote.insert.assert_called_once()

    @patch('services.review_service.Review')
    @patch('services.review_service.ReviewVote')
    async def test_delete_review(self, mock_vote_cls, mock_review_cls, mock_beanie):
        mock_review = MagicMock()
        mock_review.user_id = uuid4()
        mock_review.delete = AsyncMock()
        mock_review_cls.get = AsyncMock(return_value=mock_review)

        mock_vote_query = MagicMock()
        mock_vote_query.delete = AsyncMock()
        mock_vote_cls.find = MagicMock(return_value=mock_vote_query)

        from services.review_service import delete_review

        review_id = uuid4()
        user_id = mock_review.user_id
        result = await delete_review(review_id, user_id)

        assert result is True
        mock_review.delete.assert_called_once()
        mock_vote_query.delete.assert_called_once()

    @patch('services.review_service.Review')
    async def test_delete_review_not_owner(self, mock_review_cls, mock_beanie):
        mock_review = MagicMock()
        mock_review.user_id = uuid4()  # другой пользователь
        mock_review_cls.get = AsyncMock(return_value=mock_review)

        from services.review_service import delete_review

        review_id = uuid4()
        other_user = uuid4()
        result = await delete_review(review_id, other_user)

        assert result is False
