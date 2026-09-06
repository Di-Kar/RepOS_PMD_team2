"""Тесты для сервиса лайков (like_service)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def sample_film_id():
    """UUID тестового фильма."""
    return uuid4()


@pytest.fixture
def mock_aggregate_result_with_data():
    """Результат агрегации с данными (есть лайки)."""
    return [
        {
            "summary": [
                {
                    "total_ratings": 5,
                    "rating_sum": 40,
                    "total_likes": 3,
                    "total_dislikes": 1,
                    "average_rating": 8.0,
                }
            ],
            "distribution": [
                {"_id": 6, "count": 1},
                {"_id": 7, "count": 1},
                {"_id": 8, "count": 2},
                {"_id": 9, "count": 1},
            ],
        }
    ]


@pytest.fixture
def mock_aggregate_result_empty():
    """Результат агрегации без данных (нет лайков)."""
    return [
        {
            "summary": [
                {
                    "total_ratings": 0,
                    "rating_sum": 0,
                    "total_likes": 0,
                    "total_dislikes": 0,
                    "average_rating": 0,
                }
            ],
            "distribution": [],
        }
    ]


class TestGetFilmLikeStats:
    """Тесты функции get_film_like_stats."""

    @pytest.mark.asyncio
    async def test_returns_correct_stats_with_ratings(self, sample_film_id, mock_aggregate_result_with_data):
        """Проверяет корректный расчёт метрик при наличии оценок."""
        from services.like_service import get_film_like_stats

        # Мокаем курсор агрегации
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=mock_aggregate_result_with_data)

        # Мокаем collection.aggregate
        mock_collection = MagicMock()
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        with patch('services.like_service.Like', collection=mock_collection):
            result = await get_film_like_stats(sample_film_id)

        # Проверяем, что пайплайн передан корректно
        mock_collection.aggregate.assert_called_once()
        pipeline = mock_collection.aggregate.call_args[0][0]
        assert len(pipeline) == 2
        assert pipeline[0]["$match"]["film_id"] == sample_film_id
        assert "$facet" in pipeline[1]

        # Проверяем результаты
        assert result['film_id'] == str(sample_film_id)
        assert result['total_ratings'] == 5
        assert result['total_likes'] == 3
        assert result['total_dislikes'] == 1
        assert result['average_rating'] == 8.0
        assert result['rating_distribution'][8] == 2
        assert result['rating_distribution'][9] == 1
        assert result['rating_distribution'][6] == 1
        assert result['rating_distribution'][7] == 1
        # Неиспользуемые оценки = 0
        assert result['rating_distribution'][0] == 0
        assert result['rating_distribution'][10] == 0

    @pytest.mark.asyncio
    async def test_returns_zero_stats_when_no_ratings(self, sample_film_id, mock_aggregate_result_empty):
        """Проверяет нулевые метрики при отсутствии оценок."""
        from services.like_service import get_film_like_stats

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=mock_aggregate_result_empty)

        mock_collection = MagicMock()
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        with patch('services.like_service.Like', collection=mock_collection):
            result = await get_film_like_stats(sample_film_id)

        assert result['total_ratings'] == 0
        assert result['total_likes'] == 0
        assert result['total_dislikes'] == 0
        assert result['average_rating'] == 0.0
        # Все значения распределения = 0
        for count in result['rating_distribution'].values():
            assert count == 0

    @pytest.mark.asyncio
    async def test_handles_empty_aggregation_result(self, sample_film_id):
        """Проверяет обработку пустого результата агрегации."""
        from services.like_service import get_film_like_stats

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        mock_collection = MagicMock()
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        with patch('services.like_service.Like', collection=mock_collection):
            result = await get_film_like_stats(sample_film_id)

        assert result['total_ratings'] == 0
        assert result['total_likes'] == 0
        assert result['total_dislikes'] == 0
        assert result['average_rating'] == 0.0
        assert result['film_id'] == str(sample_film_id)

    @pytest.mark.asyncio
    async def test_distribution_contains_all_ratings_0_to_10(self, sample_film_id):
        """Проверяет, что распределение содержит ключи от 0 до 10."""
        from services.like_service import get_film_like_stats

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {
                "summary": [{"total_ratings": 1, "rating_sum": 5, "total_likes": 0, "total_dislikes": 0, "average_rating": 5.0}],
                "distribution": [{"_id": 5, "count": 1}],
            }
        ])

        mock_collection = MagicMock()
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        with patch('services.like_service.Like', collection=mock_collection):
            result = await get_film_like_stats(sample_film_id)

        distribution = result['rating_distribution']
        assert len(distribution) == 11
        for i in range(11):
            assert i in distribution
        assert distribution[5] == 1
        for i in range(11):
            if i != 5:
                assert distribution[i] == 0
