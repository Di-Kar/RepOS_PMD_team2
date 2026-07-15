"""Выпуск и валидация JWT-токенов, управление сессиями в Redis.

Схема хранения:
    auth:sessions:{user_id}:{session_id} -> jti текущего refresh-токена (TTL = срок refresh)

Активные access-токены нигде не хранятся: access валиден, пока
жив ключ его сессии в Redis. Поэтому logout / logout-all мгновенно
инвалидируют и access-токены (через session_id внутри токена).
Ротация refresh: при обмене значение ключа заменяется на новый jti,
старый refresh становится бесполезным (jti не совпадает).
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import jwt
from redis.asyncio import Redis

from src.core.config import settings
from src.core.exceptions import InvalidTokenError
from src.models.entity import User
from src.models.schemas import TokenPayload

SESSION_KEY = "auth:sessions:{user_id}:{session_id}"
SESSION_KEY_PATTERN = "auth:sessions:{user_id}:*"


class TokenService:
    """Создание, проверка и отзыв пар access/refresh токенов."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # --- выпуск токенов ---

    def _encode(
        self,
        user: User,
        roles: List[str],
        token_type: str,
        session_id: str,
        jti: str,
        expires_delta: timedelta,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.id),
            "login": user.login,
            "roles": roles,
            "token_type": token_type,
            "jti": jti,
            "session_id": session_id,
            "exp": int((now + expires_delta).timestamp()),
            "iat": int(now.timestamp()),
        }
        return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    async def create_token_pair(
        self, user: User, roles: List[str], session_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """Выпускает пару токенов и регистрирует (или продлевает) сессию в Redis."""
        session_id = session_id or str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())

        access_token = self._encode(
            user,
            roles,
            "access",
            session_id,
            str(uuid.uuid4()),
            timedelta(minutes=settings.access_token_expire_minutes),
        )
        refresh_token = self._encode(
            user,
            roles,
            "refresh",
            session_id,
            refresh_jti,
            timedelta(days=settings.refresh_token_expire_days),
        )

        await self._redis.set(
            SESSION_KEY.format(user_id=user.id, session_id=session_id),
            refresh_jti,
            ex=timedelta(days=settings.refresh_token_expire_days),
        )
        return access_token, refresh_token

    # --- валидация ---

    def decode(self, token: str) -> TokenPayload:
        """Декодирует токен, проверяя подпись и срок действия."""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        except jwt.ExpiredSignatureError:
            raise InvalidTokenError("Token has expired")
        except jwt.PyJWTError:
            raise InvalidTokenError("Invalid token signature or format")
        return TokenPayload(**payload)

    async def validate_access_token(self, token: str) -> TokenPayload:
        """Проверяет access-токен и живость его сессии в Redis."""
        payload = self.decode(token)
        if payload.token_type != "access":
            raise InvalidTokenError("Access token expected")
        session_alive = await self._redis.exists(
            SESSION_KEY.format(user_id=payload.sub, session_id=payload.session_id)
        )
        if not session_alive:
            raise InvalidTokenError("Session has been terminated")
        return payload

    async def validate_refresh_token(self, token: str) -> TokenPayload:
        """Проверяет refresh-токен: тип, живость сессии и совпадение jti (ротация)."""
        payload = self.decode(token)
        if payload.token_type != "refresh":
            raise InvalidTokenError("Refresh token expected")

        key = SESSION_KEY.format(user_id=payload.sub, session_id=payload.session_id)
        stored_jti = await self._redis.get(key)
        if stored_jti is None:
            raise InvalidTokenError("Session has been terminated")
        if stored_jti != payload.jti:
            # Повторное использование уже ротированного refresh-токена —
            # признак компрометации, убиваем сессию целиком.
            await self._redis.delete(key)
            raise InvalidTokenError("Refresh token has already been used")
        return payload

    # --- отзыв сессий ---

    async def revoke_session(self, user_id: str, session_id: str) -> None:
        """Завершает одну сессию (logout)."""
        await self._redis.delete(SESSION_KEY.format(user_id=user_id, session_id=session_id))

    async def revoke_all_sessions(
        self, user_id: str, except_session_id: Optional[str] = None
    ) -> int:
        """Завершает все сессии пользователя, кроме указанной. Возвращает число отозванных."""
        revoked = 0
        pattern = SESSION_KEY_PATTERN.format(user_id=user_id)
        keep = (
            SESSION_KEY.format(user_id=user_id, session_id=except_session_id)
            if except_session_id
            else None
        )
        async for key in self._redis.scan_iter(match=pattern):
            if key != keep:
                await self._redis.delete(key)
                revoked += 1
        return revoked
