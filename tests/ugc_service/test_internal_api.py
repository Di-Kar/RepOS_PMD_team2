"""Тесты internal-эндпоинта агрегирующей витрины профиля (S11_T6, issue
#113): GET /api/v1/internal/users/{user_id}/ugc-summary."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.v1.internal import router
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

USER_ID = '550e8400-e29b-41d4-a716-446655440000'
FILM_ID = '550e8400-e29b-41d4-a716-446655440001'


@pytest.fixture
def app() -> FastAPI:
    """FastAPI-приложение с internal-роутером."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _mock_bookmark():
    bookmark = MagicMock()
    bookmark.film_id = FILM_ID
    bookmark.created_at = MagicMock()
    bookmark.created_at.isoformat.return_value = '2026-09-01T10:00:00'
    return bookmark


def _mock_like():
    like = MagicMock()
    like.film_id = FILM_ID
    like.rating = 8
    like.updated_at = MagicMock()
    like.updated_at.isoformat.return_value = '2026-09-01T10:00:00'
    return like


def _mock_review():
    review = MagicMock()
    review.id = '650f1a2b3c4d5e6f7a8b9c0d'
    review.user_id = USER_ID
    review.film_id = FILM_ID
    review.title = 'Отличный фильм'
    review.text = 'Прекрасная история'
    review.rating = 9
    review.published_at = MagicMock()
    review.published_at.isoformat.return_value = '2026-09-01T10:00:00'
    review.likes_count = 3
    review.dislikes_count = 0
    review.is_spoiler = False
    return review


class TestGetUserUgcSummary:
    """Тесты endpoint GET /api/v1/internal/users/{user_id}/ugc-summary."""

    @patch('api.v1.internal.review_service')
    @patch('api.v1.internal.like_service')
    @patch('api.v1.internal.bookmark_service')
    def test_aggregates_all_three_sources(
        self, mock_bookmark_service, mock_like_service, mock_review_service, client
    ):
        mock_bookmark_service.get_user_bookmarks = AsyncMock(
            return_value=[_mock_bookmark()]
        )
        mock_like_service.get_user_likes = AsyncMock(return_value=[_mock_like()])
        mock_review_service.get_user_reviews = AsyncMock(
            return_value=[_mock_review()]
        )

        response = client.get(f'/api/v1/internal/users/{USER_ID}/ugc-summary')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['bookmarks'] == [
            {'film_id': FILM_ID, 'added_at': '2026-09-01T10:00:00'}
        ]
        assert data['ratings'] == [
            {'film_id': FILM_ID, 'rating': 8, 'updated_at': '2026-09-01T10:00:00'}
        ]
        assert data['reviews'][0]['title'] == 'Отличный фильм'
        assert data['reviews'][0]['rating'] == 9

    @patch('api.v1.internal.review_service')
    @patch('api.v1.internal.like_service')
    @patch('api.v1.internal.bookmark_service')
    def test_user_without_ugc_data_returns_empty_lists(
        self, mock_bookmark_service, mock_like_service, mock_review_service, client
    ):
        mock_bookmark_service.get_user_bookmarks = AsyncMock(return_value=[])
        mock_like_service.get_user_likes = AsyncMock(return_value=[])
        mock_review_service.get_user_reviews = AsyncMock(return_value=[])

        response = client.get(f'/api/v1/internal/users/{USER_ID}/ugc-summary')

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {'bookmarks': [], 'ratings': [], 'reviews': []}

    @patch('api.v1.internal.review_service')
    @patch('api.v1.internal.like_service')
    @patch('api.v1.internal.bookmark_service')
    def test_limit_param_forwarded_to_each_service(
        self, mock_bookmark_service, mock_like_service, mock_review_service, client
    ):
        mock_bookmark_service.get_user_bookmarks = AsyncMock(return_value=[])
        mock_like_service.get_user_likes = AsyncMock(return_value=[])
        mock_review_service.get_user_reviews = AsyncMock(return_value=[])

        response = client.get(
            f'/api/v1/internal/users/{USER_ID}/ugc-summary', params={'limit': 5}
        )

        assert response.status_code == status.HTTP_200_OK
        mock_bookmark_service.get_user_bookmarks.assert_awaited_once()
        assert mock_bookmark_service.get_user_bookmarks.await_args.kwargs['limit'] == 5
        assert mock_like_service.get_user_likes.await_args.kwargs['limit'] == 5
        assert mock_review_service.get_user_reviews.await_args.kwargs['limit'] == 5

    def test_invalid_user_id_returns_422(self, client: TestClient):
        response = client.get('/api/v1/internal/users/not-a-uuid/ugc-summary')
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_limit_out_of_bounds_returns_422(self, client: TestClient):
        response = client.get(
            f'/api/v1/internal/users/{USER_ID}/ugc-summary', params={'limit': 101}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestInternalApiKeyGuard:
    """verify_internal_api_key отклоняет запрос, когда UGC_INTERNAL_API_KEY
    задан — в отличие от остальных internal-роутов проекта, где эта ветка
    нигде не покрыта тестами (ключ всегда пуст в dev/test-окружении), здесь
    проверяем явно: это единственная защита от выдачи чужих
    закладок/оценок/рецензий по произвольному user_id."""

    @pytest.fixture(autouse=True)
    def configured_key(self):
        from api import dependencies

        original = dependencies.settings.internal_api_key
        dependencies.settings.internal_api_key = 'secret-key'
        yield
        dependencies.settings.internal_api_key = original

    def test_missing_header_returns_401(self, client: TestClient):
        response = client.get(f'/api/v1/internal/users/{USER_ID}/ugc-summary')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()['detail']['error'] == 'invalid_internal_api_key'

    def test_wrong_header_returns_401(self, client: TestClient):
        response = client.get(
            f'/api/v1/internal/users/{USER_ID}/ugc-summary',
            headers={'X-Internal-Api-Key': 'wrong-key'},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch('api.v1.internal.review_service')
    @patch('api.v1.internal.like_service')
    @patch('api.v1.internal.bookmark_service')
    def test_correct_header_returns_200(
        self, mock_bookmark_service, mock_like_service, mock_review_service, client
    ):
        mock_bookmark_service.get_user_bookmarks = AsyncMock(return_value=[])
        mock_like_service.get_user_likes = AsyncMock(return_value=[])
        mock_review_service.get_user_reviews = AsyncMock(return_value=[])

        response = client.get(
            f'/api/v1/internal/users/{USER_ID}/ugc-summary',
            headers={'X-Internal-Api-Key': 'secret-key'},
        )
        assert response.status_code == status.HTTP_200_OK
