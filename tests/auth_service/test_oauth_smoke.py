"""HTTP-смоук-тесты /api/v1/auth/oauth. Без реальных Google-креденшлов —
только проверка формы редиректа и защиты unlink-эндпоинта."""

from .conftest import BASE_URL, bearer


class TestGoogleLoginRedirect:
    async def test_redirects_to_google(self, session):
        async with session.get(
            f"{BASE_URL}/auth/oauth/google/login", allow_redirects=False
        ) as response:
            assert response.status in (302, 307), await response.text()
            location = response.headers["Location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "client_id=" in location
        assert "state=" in location
        assert "nonce=" in location


class TestUnlinkSocialAccount:
    async def test_requires_token(self, session):
        async with session.delete(f"{BASE_URL}/auth/oauth/google") as response:
            assert response.status == 401

    async def test_unknown_provider(self, session, shared_tokens):
        async with session.delete(
            f"{BASE_URL}/auth/oauth/unknown_provider", headers=bearer(shared_tokens)
        ) as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "unknown_provider"

    async def test_not_linked(self, session, shared_tokens):
        # shared_user заведён по паролю, без привязанных соцаккаунтов.
        async with session.delete(
            f"{BASE_URL}/auth/oauth/google", headers=bearer(shared_tokens)
        ) as response:
            assert response.status == 404
            body = await response.json()
        assert body["detail"]["error"] == "not_linked"
