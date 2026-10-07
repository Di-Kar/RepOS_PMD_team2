"""HTTP-клиент к ugc_service для карточки фильма: статистика и рецензии.

Эндпоинты чтения ugc публичные, токен не нужен. Таймаут + circuit breaker:
при сбое возвращается None, и карточка отдаётся без UGC-блока.
"""

import logging
from typing import Any, Optional
from uuid import UUID

import httpx
from core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class UgcClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, transport=transport
        )
        self._breaker = CircuitBreaker(failure_threshold=5, reset_timeout=30.0)

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        if not self._breaker.allow_request():
            logger.debug('ugc_service circuit breaker открыт — UGC-блок пропущен')
            return None
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            logger.warning('ugc_service недоступен: %s', exc)
            self._breaker.record_failure()
            return None

        if response.status_code >= 500:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        if response.status_code != 200:
            logger.warning('ugc_service вернул %s на %s', response.status_code, path)
            return None
        return response.json()

    async def get_film_stats(self, film_id: UUID) -> Optional[dict]:
        """GET /api/v1/likes/{film_id}: average_rating, total_ratings и т.д."""
        return await self._get(f'/likes/{film_id}')

    async def get_film_reviews(
        self, film_id: UUID, sort: str, page_number: int, page_size: int
    ) -> Optional[list[dict]]:
        """GET /api/v1/reviews — список рецензий фильма с сортировкой и пагинацией."""
        return await self._get(
            '/reviews',
            params={
                'film_id': str(film_id),
                'sort': sort,
                'page_number': page_number,
                'page_size': page_size,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()
