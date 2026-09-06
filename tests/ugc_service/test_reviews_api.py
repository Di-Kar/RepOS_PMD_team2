"""Тесты API endpoint'ов рецензий: валидация ObjectId и body-параметров."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.dependencies import UserContext
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


@pytest.fixture
def mock_user():
    """Мокаемый контекст пользователя для авторизованных запросов."""
    return UserContext(user_id='550e8400-e29b-41d4-a716-446655440000', name='Test User')


@pytest.fixture
def authed_client(client: TestClient, mock_user) -> TestClient:
    """TestClient с замоканной авторизацией через заголовок Authorization."""
    auth_client_mock = MagicMock(get_current_user=AsyncMock(return_value=mock_user))
    with patch('api.dependencies._auth_client', auth_client_mock):
        # Добавляем заголовок Authorization ко всем запросам
        client.headers['Authorization'] = 'Bearer test-token'
        yield client


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


# ==================================================================== #
#  POST '' — создание рецензии (request body)                           #
# ==================================================================== #


class TestCreateReview:
    """Тесты endpoint POST '' (создание рецензии)."""

    @patch('api.v1.reviews.review_service')
    def test_valid_body_returns_201(
        self, mock_service: MagicMock, authed_client: TestClient
    ):
        """Валидный body → 201 с данными рецензии."""
        mock_review = MagicMock()
        mock_review.id = ObjectId('550e8400e29b41d4a7164466')
        mock_review.user_id = '550e8400-e29b-41d4-a716-446655440000'
        mock_review.film_id = '550e8400-e29b-41d4-a716-446655440001'
        mock_review.title = 'Отличный фильм'
        mock_review.text = 'Прекрасная история'
        mock_review.rating = 9
        mock_review.published_at = MagicMock()
        mock_review.published_at.isoformat.return_value = '2024-01-01T12:00:00'
        mock_review.likes_count = 10
        mock_review.dislikes_count = 1

        mock_service.create_review = AsyncMock(return_value=mock_review)

        response = authed_client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Отличный фильм',
                'text': 'Прекрасная история',
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['title'] == 'Отличный фильм'
        assert data['rating'] == 9
        assert data['film_id'] == '550e8400-e29b-41d4-a716-446655440001'

    @patch('api.v1.reviews.review_service')
    def test_missing_required_field_returns_422(self, mock_service, client: TestClient):
        """Отсутствующее обязательное поле → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Отличный фильм',
                # text отсутствует
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, list)

    @patch('api.v1.reviews.review_service')
    def test_invalid_film_id_returns_422(self, mock_service, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': 'not-a-uuid',
                'title': 'Отличный фильм',
                'text': 'Текст',
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, list)

    @patch('api.v1.reviews.review_service')
    def test_rating_out_of_bounds_returns_422(self, mock_service, client: TestClient):
        """Рейтинг вне диапазона 0-10 → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Отличный фильм',
                'text': 'Текст',
                'rating': 11,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('api.v1.reviews.review_service')
    def test_empty_title_returns_422(self, mock_service, client: TestClient):
        """Пустой заголовок → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': '',
                'text': 'Текст',
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('api.v1.reviews.review_service')
    def test_title_too_long_returns_422(self, mock_service, client: TestClient):
        """Заголовок длиннее 200 символов → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'A' * 201,
                'text': 'Текст',
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('api.v1.reviews.review_service')
    def test_text_too_long_returns_422(self, mock_service, client: TestClient):
        """Текст длиннее 10000 символов → 422."""
        response = client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Заголовок',
                'text': 'T' * 10001,
                'rating': 9,
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('api.v1.reviews.review_service')
    def test_long_text_accepted_within_limit(
        self, mock_service: MagicMock, authed_client: TestClient
    ):
        """Текст ровно 10000 символов → 201 (в пределах лимита)."""
        mock_review = MagicMock()
        mock_review.id = ObjectId('550e8400e29b41d4a7164466')
        mock_review.user_id = '550e8400-e29b-41d4-a716-446655440000'
        mock_review.film_id = '550e8400-e29b-41d4-a716-446655440001'
        mock_review.title = 'Длинный текст'
        mock_review.text = 'T' * 10000
        mock_review.rating = 8
        mock_review.published_at = MagicMock()
        mock_review.published_at.isoformat.return_value = '2024-01-01T12:00:00'
        mock_review.likes_count = 0
        mock_review.dislikes_count = 0

        mock_service.create_review = AsyncMock(return_value=mock_review)

        response = authed_client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Длинный текст',
                'text': 'T' * 10000,
                'rating': 8,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['title'] == 'Длинный текст'

    @patch('api.v1.reviews.review_service')
    def test_body_accepted_not_query_params(
        self, mock_service: MagicMock, authed_client: TestClient
    ):
        """Проверка, что данные принимаются через body (JSON), а не query params."""
        mock_review = MagicMock()
        mock_review.id = ObjectId('550e8400e29b41d4a7164466')
        mock_review.user_id = '550e8400-e29b-41d4-a716-446655440000'
        mock_review.film_id = '550e8400-e29b-41d4-a716-446655440001'
        mock_review.title = 'Тест body'
        mock_review.text = 'Текст'
        mock_review.rating = 7
        mock_review.published_at = MagicMock()
        mock_review.published_at.isoformat.return_value = '2024-01-01T12:00:00'
        mock_review.likes_count = 0
        mock_review.dislikes_count = 0

        mock_service.create_review = AsyncMock(return_value=mock_review)

        # Отправляем через body (json=), а не params=
        response = authed_client.post(
            '/api/v1/reviews',
            json={
                'film_id': '550e8400-e29b-41d4-a716-446655440001',
                'title': 'Тест body',
                'text': 'Текст',
                'rating': 7,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data['title'] == 'Тест body'
