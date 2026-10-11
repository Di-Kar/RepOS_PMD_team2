"""Тесты API endpoint'ов закладок: валидация UUID, film_title и sort."""

from unittest.mock import patch

import pytest
from api.v1.bookmarks import EXAMPLE_FILM_ID, router
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

# ==================================================================== #
#  Фикстуры                                                            #
# ==================================================================== #


@pytest.fixture
def app() -> FastAPI:
    """FastAPI-приложение с роутером закладок."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """TestClient для отправки запросов к приложению."""
    return TestClient(app)


# ==================================================================== #
#  POST '' — добавить закладку                                         #
# ==================================================================== #


class TestAddBookmark:
    """Тесты endpoint POST '' (добавить закладку)."""

    @patch('api.v1.bookmarks.bookmark_service')
    def test_invalid_film_id_returns_422(self, mock_service, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.post(
            '/api/v1/bookmarks',
            params={'film_id': 'not-a-uuid', 'film_title': 'Интерстеллар'},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = response.json()['detail']
        assert isinstance(detail, list)

    @patch('api.v1.bookmarks.bookmark_service')
    def test_missing_film_title_returns_422(self, mock_service, client: TestClient):
        """Без film_title (S11_T13, issue #120) → 422."""
        response = client.post(
            '/api/v1/bookmarks',
            params={'film_id': str(EXAMPLE_FILM_ID)},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==================================================================== #
#  GET '' — список закладок                                            #
# ==================================================================== #


class TestGetBookmarks:
    """Тесты endpoint GET '' (список закладок): валидация sort."""

    def test_invalid_sort_returns_422(self, client: TestClient):
        """Невалидное значение sort (S11_T13, issue #120) → 422."""
        response = client.get('/api/v1/bookmarks', params={'sort': 'drop_table'})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ==================================================================== #
#  DELETE /{film_id} — удалить закладку                                #
# ==================================================================== #


class TestRemoveBookmark:
    """Тесты endpoint DELETE /{film_id}."""

    def test_invalid_film_id_returns_422(self, client: TestClient):
        """Невалидный UUID film_id → 422."""
        response = client.delete('/api/v1/bookmarks/not-a-uuid')

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# GET '' требует авторизации — проверяется в E2E-тестах
