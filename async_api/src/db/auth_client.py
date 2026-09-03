"""HTTP-клиент к auth_service для проверки access-токена.

Подпись JWT не проверяется локально — каждый запрос с Authorization идёт
через GET /profile, чтобы logout был виден сразу. Короткий таймаут +
circuit breaker: при любой проблеме с auth_service запрос просто
обслуживается как анонимный (см. get_current_user).
"""
import logging
from typing import List, Optional

import httpx
from core.circuit_breaker import CircuitBreaker
from fastapi import Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class UserContext(BaseModel):
    """Данные пользователя, полученные от auth_service."""

    user_id: str
    login: Optional[str] = None
    full_name: Optional[str] = None
    roles: List[str] = []
    is_superuser: bool = False


class AuthServiceClient:
    """Обёртка над httpx.AsyncClient с circuit breaker."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._breaker = CircuitBreaker(failure_threshold=5, reset_timeout=30.0)

    async def get_current_user(self, token: str) -> Optional[UserContext]:
        if not token:
            return None
        if not self._breaker.allow_request():
            logger.debug('auth_service circuit breaker открыт — считаем пользователя анонимным')
            return None
        try:
            response = await self._client.get(
                '/profile', headers={'Authorization': f'Bearer {token}'}
            )
        except httpx.HTTPError as exc:
            logger.warning('auth_service недоступен: %s', exc)
            self._breaker.record_failure()
            return None

        self._breaker.record_success()
        if response.status_code != 200:
            return None

        data = response.json()
        return UserContext(
            user_id=str(data['id']),
            login=data.get('email'),
            full_name=data.get('full_name'),
            roles=data.get('roles') or [],
            is_superuser=data.get('is_superuser', False),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def get_auth_client(request: Request) -> AuthServiceClient:
    return request.app.state.auth_client
