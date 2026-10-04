import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime

from main import app
from api.dependencies import UserContext


@pytest.fixture(autouse=True)
def mock_db_init():
    """Мокаем инициализацию MongoDB при старте приложения."""
    with patch("db.connection.init_db", new_callable=AsyncMock), \
         patch("db.init_db.init_cluster", new_callable=AsyncMock), \
         patch("db.connection.close_db", new_callable=AsyncMock):
        yield


@pytest.fixture
def mock_review_service():
    """Мокаем сохранение рецензии в БД, чтобы не требовать реальную MongoDB."""
    mock_review = MagicMock()
    mock_review.id = "60c72b2f9b1e8b001c8e4d5a"
    mock_review.user_id = uuid4()
    mock_review.film_id = uuid4()
    mock_review.title = "Test Review"
    mock_review.rating = 8
    mock_review.published_at = datetime.now()
    mock_review.likes_count = 0
    mock_review.dislikes_count = 0
    
    with patch("api.v1.reviews.review_service.create_review", new_callable=AsyncMock, return_value=mock_review):
        yield


@pytest.fixture
def strict_limit():
    """В тестах ставим жёсткий лимит 2/minute. Теперь это сработает благодаря lambda в reviews.py"""
    with patch("config.settings.reviews_rate_limit", "2/minute"):
        yield


@pytest.fixture
def mock_auth():
    """Мокаем авторизацию с валидным UUID."""
    valid_uuid = str(uuid4())
    mock_client = type('MockClient', (), {
        'get_current_user': AsyncMock(return_value=UserContext(user_id=valid_uuid, name="Test"))
    })()
    
    with patch("main.get_auth_client", return_value=mock_client) as mock_getter:
        yield mock_getter


@pytest.mark.asyncio
async def test_create_review_within_limit(strict_limit, mock_db_init, mock_auth, mock_review_service):
    """Пользователь может создать 2 рецензии в пределах лимита."""
    headers = {"Authorization": "Bearer valid_token"}
    payload = {
        "film_id": str(uuid4()),
        "title": "Test Review",
        "text": "Great movie!",
        "rating": 8
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for i in range(2):
            payload["text"] = f"review {i}"
            r = await ac.post("/api/v1/reviews", json=payload, headers=headers)
            assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_review_exceeds_limit_returns_429(strict_limit, mock_db_init, mock_auth, mock_review_service):
    """Третий запрос должен вернуть 429."""
    headers = {"Authorization": "Bearer valid_token"}
    payload = {
        "film_id": str(uuid4()),
        "title": "Test Review",
        "text": "Great movie!",
        "rating": 8
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for i in range(2):
            payload["text"] = f"review {i}"
            await ac.post("/api/v1/reviews", json=payload, headers=headers)
        
        payload["text"] = "spam"
        r = await ac.post("/api/v1/reviews", json=payload, headers=headers)
        
        assert r.status_code == 429, r.text
        body = r.json()
        assert body["error"] == "rate_limit_exceeded"
        assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_rate_limit_is_per_user(strict_limit, mock_db_init, mock_review_service):
    """Лимит персональный: разные токены = разные лимиты."""
    payload = {
        "film_id": str(uuid4()),
        "title": "Test Review",
        "text": "Great movie!",
        "rating": 8
    }
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        
        # --- User A исчерпывает лимит ---
        user_a_uuid = str(uuid4())
        mock_client_a = type('MockClient', (), {
            'get_current_user': AsyncMock(return_value=UserContext(user_id=user_a_uuid, name="A"))
        })()
        with patch("main.get_auth_client", return_value=mock_client_a):
            for i in range(2):
                payload["text"] = f"review A{i}"
                await ac.post("/api/v1/reviews", json=payload, headers={"Authorization": "Bearer token_A"})
            
            payload["text"] = "spam A"
            r_a = await ac.post("/api/v1/reviews", json=payload, headers={"Authorization": "Bearer token_A"})
            assert r_a.status_code == 429, r_a.text

        # --- User B ещё может писать ---
        user_b_uuid = str(uuid4())
        mock_client_b = type('MockClient', (), {
            'get_current_user': AsyncMock(return_value=UserContext(user_id=user_b_uuid, name="B"))
        })()
        with patch("main.get_auth_client", return_value=mock_client_b):
            payload["text"] = "review B"
            r_b = await ac.post("/api/v1/reviews", json=payload, headers={"Authorization": "Bearer token_B"})
            assert r_b.status_code == 201, r_b.text