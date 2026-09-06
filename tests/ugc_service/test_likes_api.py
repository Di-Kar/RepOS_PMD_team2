"""Тесты API endpoint'ов лайков: валидация UUID."""

from unittest.mock import AsyncMock, patch

import pytest
from api.v1.likes import router
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

# ==================================================================== #
#  Фикстуры                                                            #
# ==================================================================== #


@pytest.fixture
def app() -> FastAPI:
    """FastAPI-приложение с роутером лайков."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """TestClient для отправки запросов к приложению."""
    return TestClient(app)


# ==================================================================== #
#  POST '' — добавить/обновить лайк                                    #
# ==================================================================== #


class TestAddLike:
    """Тесты endpoint POST '' (добавить лайк)."""

    @patch('api.v1.likes.like_service')
    def test_invalid_film_id_returns_422(self, mock_service, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.post(
            '/api/v1/likes',
            params={'film_id': 'not-a-uuid'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, list)


# ==================================================================== #
#  DELETE /{film_id} — удалить лайк                                    #
# ==================================================================== #


class TestRemoveLike:
    """Тесты endpoint DELETE /{film_id}."""

    def test_invalid_film_id_returns_422(self, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.delete('/api/v1/likes/not-a-uuid')

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==================================================================== #
#  GET /{film_id} — статистика лайков                                  #
# ==================================================================== #


class TestGetLikeStats:
    """Тесты endpoint GET /{film_id} (статистика лайков)."""

    def test_invalid_film_id_returns_422(self, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.get('/api/v1/likes/not-a-uuid')

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, list)

    @patch('api.v1.likes.like_service')
    def test_valid_request_returns_200(self, mock_service, client: TestClient):
        """Валидный запрос → 200 со статистикой."""
        mock_service.get_film_like_stats = AsyncMock(
            return_value={
                'film_id': '550e8400-e29b-41d4-a716-446655440000',
                'total_likes': 10,
                'total_dislikes': 2,
                'average_rating': 7.5,
                'total_ratings': 12,
                'rating_distribution': {
                    0: 0, 1: 0, 2: 0, 3: 1, 4: 0, 5: 1, 6: 0, 7: 3, 8: 4, 9: 2, 10: 1
                },
            }
        )

        valid_uuid = '550e8400-e29b-41d4-a716-446655440000'
        response = client.get(f'/api/v1/likes/{valid_uuid}')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['film_id'] == valid_uuid
        assert data['total_likes'] == 10
