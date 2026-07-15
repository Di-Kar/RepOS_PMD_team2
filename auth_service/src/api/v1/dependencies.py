"""
Зависимости авторизации для IDM-роутов.

ВРЕМЕННЫЙ СТАБ: get_current_user() не проверяет JWT, а достаёт пользователя
по заголовку X-User-Id. Когда auth-часть выдачи/валидации токенов будет
готова, эта функция заменяется на реальную проверку Bearer-токена
(формат payload уже зафиксирован в TokenPayload, schemas.py) — роуты,
использующие Depends(get_current_user), менять не придётся.
"""
import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.postgres import get_session
from src.models.entity import User


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Временная замена проверки access-токена."""
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "X-User-Id header is required"},
        )

    try:
        user_id = uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "X-User-Id must be a valid UUID"},
        )

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "User not found or inactive"},
        )
    return user


async def require_superuser(user: User = Depends(get_current_user)) -> User:
    """Требует, чтобы текущий пользователь был суперпользователем."""
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Superuser privileges required"},
        )
    return user
