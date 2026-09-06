"""Тесты API endpoint'ов рецензий: валидация ObjectId."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.v1.reviews import router
from bson import ObjectId
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

# ==================================================================== #
#  Фикстуры                                                            #
# ==================================================================== #


@pytest.fixture
def app() -> FastAPI:
    """FastAPI-приложение с роутером рецензий."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """TestClient для отправки запросов к приложению."""
    return TestClient(app)


# ==================================================================== #
#  GET /{review_id} — детали рецензии                                  #
# ==================================================================== #


class TestGetReview:
    """Тесты endpoint GET /{review_id}."""

    def test_invalid_object_id_returns_422(self, client: TestClient):
        """Невалидный ObjectId → 422 Unprocessable Entity."""
        response = client.get('/api/v1/reviews/not-an-id')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, str)
        assert 'ObjectId' in detail

    def test_non_hex_object_id_returns_422(self, client: TestClient):
        """Строка с не-hex символами → 422."""
        response = client.get('/api/v1/reviews/abc123xyz')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('api.v1.reviews.review_service')
    def test_valid_object_id_returns_review(self, mock_service, client: TestClient):
        """Валидный ObjectId → 200 с данными рецензии."""
        mock_review = MagicMock()
        mock_review.id = ObjectId('550e8400e29b41d4a7164466')
        mock_review.user_id = '550e8400-e29b-41d4-a716-446655440000'
        mock_review.film_id = '550e8400-e29b-41d4-a716-446655440001'
        mock_review.title = 'Отличный фильм'
        mock_review.text = 'Очень хороший фильм'
        mock_review.rating = 9
        mock_review.published_at = MagicMock()
        mock_review.published_at.isoformat.return_value = '2024-01-01T12:00:00'
        mock_review.likes_count = 10
        mock_review.dislikes_count = 1

        mock_service.get_review_by_id = AsyncMock(return_value=mock_review)

        valid_id = '550e8400e29b41d4a7164466'
        response = client.get(f'/api/v1/reviews/{valid_id}')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['title'] == 'Отличный фильм'
        assert data['rating'] == 9

    @patch('api.v1.reviews.review_service')
    def test_valid_object_id_not_found_returns_404(
        self, mock_service, client: TestClient
    ):
        """Валидный ObjectId, но рецензия не найдена → 404."""
        mock_service.get_review_by_id = AsyncMock(return_value=None)

        valid_id = '550e8400e29b41d4a7164466'
        response = client.get(f'/api/v1/reviews/{valid_id}')

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()['detail'] == 'Рецензия не найдена'


# ==================================================================== #
#  PUT /{review_id} — обновление рецензии                              #
# ==================================================================== #


class TestUpdateReview:
    """Тесты endpoint PUT /{review_id}."""

    def test_invalid_object_id_returns_422(self, client: TestClient):
        """Невалидный ObjectId → 422 (до проверки авторизации)."""
        response = client.put(
            '/api/v1/reviews/not-an-id',
            json={'title': 'Обновлённый заголовок'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, str)
        assert 'ObjectId' in detail

    def test_non_hex_object_id_returns_422(self, client: TestClient):
        """Не-hex строка → 422."""
        response = client.put(
            '/api/v1/reviews/invalid-id-here',
            json={'title': 'Обновлённый заголовок'},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==================================================================== #
#  DELETE /{review_id} — удаление рецензии                             #
# ==================================================================== #


class TestDeleteReview:
    """Тесты endpoint DELETE /{review_id}."""

    def test_invalid_object_id_returns_422(self, client: TestClient):
        """Невалидный ObjectId → 422 (до проверки авторизации)."""
        response = client.delete('/api/v1/reviews/not-an-id')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, str)
        assert 'ObjectId' in detail

    def test_non_hex_object_id_returns_422(self, client: TestClient):
        """Не-hex строка → 422."""
        response = client.delete('/api/v1/reviews/bad-value')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==================================================================== #
#  POST /{review_id}/vote — голосование                                #
# ==================================================================== #


class TestVoteOnReview:
    """Тесты endpoint POST /{review_id}/vote."""

    def test_invalid_object_id_returns_422(self, client: TestClient):
        """Невалидный ObjectId → 422 (до проверки авторизации)."""
        response = client.post('/api/v1/reviews/not-an-id/vote')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, str)
        assert 'ObjectId' in detail

    def test_non_hex_object_id_returns_422(self, client: TestClient):
        """Не-hex строка → 422."""
        response = client.post('/api/v1/reviews/xyz123/vote')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
