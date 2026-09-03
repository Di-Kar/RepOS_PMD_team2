"""Выпуск и валидация JWT-токенов, управление сессиями в Redis.

Схема хранения:
    auth:sessions:{user_id}:{session_id} -> jti текущего refresh-токена (TTL = срок refresh)

Активные access-токены нигде не хранятся: access валиден, пока
жив ключ его сессии в Redis. Поэтому logout / logout-all мгновенно
инвалидируют и access-токены (через session_id внутри токена).
Ротация refresh: при обмене значение ключа атомарно (Lua compare-and-set)
заменяется на новый jti, старый refresh становится бесполезным (jti не
совпадает). Повторное использование ротированного токена убивает сессию.
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

# Атомарная ротация jti (compare-and-set): новый jti записывается, только если
# текущее значение совпадает с jti предъявленного refresh-токена. Иначе два
# параллельных /refresh с одним токеном оба прошли бы проверку GET-ом.
# Несовпадение — повторное использование уже ротированного токена, признак
# компрометации: сессия удаляется целиком.
_ROTATE_JTI_LUA = """
local stored = redis.call('GET', KEYS[1])
if stored == false then
    return 'missing'
end
if stored ~= ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 'reused'
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 'ok'
"""


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
            "is_superuser": user.is_superuser,
            "token_type": token_type,
            "jti": jti,
            "session_id": session_id,
            "exp": int((now + expires_delta).timestamp()),
            "iat": int(now.timestamp()),
        }
        return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    async def create_token_pair(
        self,
        user: User,
        roles: List[str],
        session_id: Optional[str] = None,
        rotate_from_jti: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Выпускает пару токенов и регистрирует (или продлевает) сессию в Redis."""
        session_id = session_id or str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())
        refresh_ttl = timedelta(days=settings.refresh_token_expire_days)

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
            refresh_ttl,
        )

        key = SESSION_KEY.format(user_id=user.id, session_id=session_id)
        if rotate_from_jti is None:
            await self._redis.set(key, refresh_jti, ex=refresh_ttl)
        else:
            result = await self._redis.eval(
                _ROTATE_JTI_LUA,
                1,
                key,
                rotate_from_jti,
                refresh_jti,
                int(refresh_ttl.total_seconds()),
            )
            if result == "missing":
                raise InvalidTokenError("Session has been terminated")
            if result != "ok":
                raise InvalidTokenError("Refresh token has already been used")
        return access_token, refresh_token

    # --- валидация ---

    def decode(self, token: str) -> TokenPayload:
        """Декодирует токен, проверяя подпись и срок действия."""
        try:
            payload = jwt.decode(
                token, settings.secret_key, algorithms=[settings.algorithm]
            )
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

        # Быстрая предпроверка; авторитетная защита от гонки — атомарный
        # compare-and-set в create_token_pair (rotate_from_jti).
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
        await self._redis.delete(
            SESSION_KEY.format(user_id=user_id, session_id=session_id)
        )

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
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            to_delete = [key for key in keys if key != keep]
            if to_delete:
                revoked += await self._redis.delete(*to_delete)
            if cursor == 0:
                break
        return revoked
