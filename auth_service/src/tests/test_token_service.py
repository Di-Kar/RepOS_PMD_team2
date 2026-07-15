"""Тесты TokenService: выпуск, валидация, ротация и отзыв сессий."""
import pytest

from src.core.exceptions import InvalidTokenError
from src.models.entity import User
from src.services.token_service import TokenService


@pytest.fixture
def token_service(redis_client) -> TokenService:
    return TokenService(redis_client)


class TestTokenService:
    async def test_create_and_validate_pair(self, token_service: TokenService, sample_user: User):
        access, refresh = await token_service.create_token_pair(sample_user, ["subscriber"])

        access_payload = await token_service.validate_access_token(access)
        assert access_payload.sub == str(sample_user.id)
        assert access_payload.login == sample_user.login
        assert access_payload.roles == ["subscriber"]
        assert access_payload.token_type == "access"

        refresh_payload = await token_service.validate_refresh_token(refresh)
        assert refresh_payload.token_type == "refresh"
        # access и refresh принадлежат одной сессии.
        assert refresh_payload.session_id == access_payload.session_id

    async def test_validate_access_rejects_refresh(
        self, token_service: TokenService, sample_user: User
    ):
        _, refresh = await token_service.create_token_pair(sample_user, [])
        with pytest.raises(InvalidTokenError):
            await token_service.validate_access_token(refresh)

    async def test_validate_rejects_garbage(self, token_service: TokenService):
        with pytest.raises(InvalidTokenError):
            token_service.decode("garbage.token.value")

    async def test_revoked_session_invalidates_access(
        self, token_service: TokenService, sample_user: User
    ):
        access, _ = await token_service.create_token_pair(sample_user, [])
        payload = await token_service.validate_access_token(access)

        await token_service.revoke_session(payload.sub, payload.session_id)
        with pytest.raises(InvalidTokenError):
            await token_service.validate_access_token(access)

    async def test_refresh_reuse_kills_session(
        self, token_service: TokenService, sample_user: User
    ):
        _, refresh = await token_service.create_token_pair(sample_user, [])
        payload = await token_service.validate_refresh_token(refresh)

        # Ротация в той же сессии: старый jti в Redis заменяется новым.
        _, new_refresh = await token_service.create_token_pair(
            sample_user, [], session_id=payload.session_id
        )
        with pytest.raises(InvalidTokenError):
            await token_service.validate_refresh_token(refresh)
        # Повторное использование убило сессию целиком — новый refresh тоже невалиден.
        with pytest.raises(InvalidTokenError):
            await token_service.validate_refresh_token(new_refresh)

    async def test_revoke_all_except_current(
        self, token_service: TokenService, sample_user: User
    ):
        access_keep, _ = await token_service.create_token_pair(sample_user, [])
        access_kill, _ = await token_service.create_token_pair(sample_user, [])
        keep_payload = await token_service.validate_access_token(access_keep)

        revoked = await token_service.revoke_all_sessions(
            keep_payload.sub, except_session_id=keep_payload.session_id
        )
        assert revoked == 1

        assert await token_service.validate_access_token(access_keep)
        with pytest.raises(InvalidTokenError):
            await token_service.validate_access_token(access_kill)
