"""Тесты rate limiting для создания рецензий."""

import pytest
import uuid
from datetime import datetime
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock

from main import app
from api.dependencies import UserContext

USER_A_ID = str(uuid.uuid4())
USER_B_ID = str(uuid.uuid4())
TEST_USER_ID = str(uuid.uuid4())


def create_mock_review(user_id, film_id, title, rating):
    """Создаёт MagicMock, имитирующий объект Review, чтобы не инициализировать Beanie."""
    mock_review = MagicMock()
    mock_review.id = uuid.uuid4()
    mock_review.user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
    mock_review.film_id = uuid.UUID(film_id) if isinstance(film_id, str) else film_id
    mock_review.title = title
    mock_review.rating = rating
    mock_review.published_at = datetime.utcnow()
    mock_review.likes_count = 0
    mock_review.dislikes_count = 0
    return mock_review


@pytest.fixture
def mock_review_service():
    """Мокаем сервис рецензий, чтобы тесты не зависели от MongoDB/Beanie."""
    with patch("api.v1.reviews.review_service.create_review", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = lambda user_id, film_id, title, text, rating: create_mock_review(
            user_id, film_id, title, rating
        )
        yield mock_create


@pytest.fixture
def strict_limit():
    """В тестах ставим жёсткий лимит 2/minute."""
    with patch("config.settings.reviews_rate_limit", "2/minute"):
        yield


@pytest.fixture
def mock_auth():
    """Мокаем успешную авторизацию для middleware."""
    with patch("api.dependencies.AuthServiceClient.get_current_user") as mock_get_user:
        mock_get_user.return_value = UserContext(user_id=TEST_USER_ID, name="Test User")
        yield mock_get_user


@pytest.mark.asyncio
async def test_create_review_within_limit(strict_limit, mock_auth, mock_review_service):
    """Пользователь может создать 2 рецензии в пределах лимита."""
    headers = {"Authorization": "Bearer valid_token"}
    film_id = str(uuid.uuid4())
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for i in range(2):
            r = await ac.post(
                "/api/v1/reviews",
                json={"film_id": film_id, "title": "Test", "text": f"review {i}", "rating": 8},
                headers=headers,
            )
            assert r.status_code == 201, f"Ожидался 201, получено: {r.status_code} - {r.text}"


@pytest.mark.asyncio
async def test_create_review_exceeds_limit_returns_429(strict_limit, mock_auth, mock_review_service):
    """Третий запрос должен вернуть 429."""
    headers = {"Authorization": "Bearer valid_token"}
    film_id = str(uuid.uuid4())
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for i in range(2):
            await ac.post(
                "/api/v1/reviews",
                json={"film_id": film_id, "title": "Test", "text": f"r{i}", "rating": 7},
                headers=headers,
            )

        r = await ac.post(
            "/api/v1/reviews",
            json={"film_id": film_id, "title": "Test", "text": "spam", "rating": 1},
            headers=headers,
        )

        assert r.status_code == 429, f"Ожидался 429, получено: {r.status_code} - {r.text}"
        body = r.json()
        assert body["error"] == "rate_limit_exceeded"
        assert r.headers["Retry-After"] == str(body["retry_after_seconds"])


@pytest.mark.asyncio
async def test_rate_limit_is_per_user(strict_limit, mock_review_service):
    """Лимит персональный: разные токены = разные лимиты."""
    film_id = str(uuid.uuid4())
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # User A исчерпывает лимит
        with patch("api.dependencies.AuthServiceClient.get_current_user") as mock_a:
            mock_a.return_value = UserContext(user_id=USER_A_ID, name="User A")
            for i in range(2):
                await ac.post("/api/v1/reviews", json={"film_id": film_id, "title": "A", "text": f"a{i}", "rating": 5}, headers={"Authorization": "Bearer token_A"})
            
            r_a = await ac.post("/api/v1/reviews", json={"film_id": film_id, "title": "A", "text": "a_spam", "rating": 5}, headers={"Authorization": "Bearer token_A"})
            assert r_a.status_code == 429, "User A должен получить 429"

        # User B ещё может писать
        with patch("api.dependencies.AuthServiceClient.get_current_user") as mock_b:
            mock_b.return_value = UserContext(user_id=USER_B_ID, name="User B")
            r_b = await ac.post("/api/v1/reviews", json={"film_id": film_id, "title": "B", "text": "b_ok", "rating": 9}, headers={"Authorization": "Bearer token_B"})
            assert r_b.status_code == 201, f"User B должен получить 201, получено: {r_b.status_code} - {r_b.text}"