"""HTTP-клиент к user_profiles: ФИО автора рецензии (S2S, X-Internal-Api-Key).

Возвращает None, если профиля нет (404) или user_profiles недоступен; вызывающая
сторона подставляет «Аноним». Таймаут + circuit breaker, как в ugc_client.
"""

import logging
from typing import Optional

import httpx
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ProfilesClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        api_key: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={'X-Internal-Api-Key': api_key},
            transport=transport,
        )
        self._breaker = CircuitBreaker(failure_threshold=5, reset_timeout=30.0)

    async def get_full_name(self, user_id: str) -> Optional[str]:
        if not self._breaker.allow_request():
            logger.debug('user_profiles circuit breaker открыт — имя не резолвим')
            return None
        try:
            response = await self._client.get(f'/{user_id}')
        except httpx.HTTPError as exc:
            logger.warning('user_profiles недоступен: %s', exc)
            self._breaker.record_failure()
            return None

        if response.status_code >= 500:
            self._breaker.record_failure()
            return None
        self._breaker.record_success()
        if response.status_code != 200:  # 404: профиля нет
            return None

        data = response.json()
        full_name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        return full_name or None

    async def aclose(self) -> None:
        await self._client.aclose()
