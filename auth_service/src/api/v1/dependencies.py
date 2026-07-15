"""Зависимости авторизации: проверка Bearer-токена и загрузка текущего пользователя."""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import InvalidTokenError
from src.db.postgres import get_session
from src.db.redis_db import get_redis
from src.models.entity import User
from src.models.schemas import TokenPayload
from src.services.token_service import TokenService

# auto_error=False, чтобы отсутствие заголовка давало 401 (а не 403 по умолчанию у HTTPBearer).
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_token", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    redis: Redis = Depends(get_redis),
) -> TokenPayload:
    """Валидирует access-токен из заголовка Authorization (подпись, срок, живость сессии)."""
    if credentials is None:
        raise _unauthorized("Authorization header with Bearer token is required")
    try:
        return await TokenService(redis).validate_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _unauthorized(str(exc))


async def get_current_user(
    payload: TokenPayload = Depends(get_token_payload),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Возвращает пользователя из валидного access-токена."""
    user = await session.get(User, uuid.UUID(payload.sub))
    if user is None or not user.is_active:
        raise _unauthorized("User not found or inactive")
    return user


async def require_superuser(user: User = Depends(get_current_user)) -> User:
    """Требует, чтобы текущий пользователь был суперпользователем."""
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Superuser privileges required"},
        )
    return user
