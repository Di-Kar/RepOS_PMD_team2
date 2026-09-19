"""HTTP-клиент к internal-эндпоинту auth_service (S10_T3, issue #96) —
воркеру из Kafka-сообщения приходит только user_id, обычный GET /profile
(JWT владельца) не подходит. См. auth_service/src/api/v1/internal.py."""

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from src.core.config import settings
from src.core.errors import PermanentProcessingError, TransientProcessingError

logger = logging.getLogger(__name__)

# Персистентный клиент на весь процесс (создаётся в init_auth_client() при
# старте main_render.py) — держит keep-alive соединение к auth_service
# вместо того, чтобы открывать новое TCP/TLS-соединение на каждый вызов
# get_user_profile (а это происходит на КАЖДОЕ сообщение requests.v1).
_client: Optional[httpx.AsyncClient] = None


async def init_auth_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=settings.auth_service_timeout)
    logger.info(f"auth_service HTTP client ready: {settings.auth_service_url}")


async def close_auth_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("auth_service HTTP client closed.")


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("auth_service HTTP client is not initialized")
    return _client


@dataclass
class UserProfile:
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool


async def get_user_profile(user_id: uuid.UUID) -> UserProfile:
    """Возвращает профиль пользователя из auth_service.

    Поднимает PermanentProcessingError на 404 (пользователь не найден —
    ретраить бессмысленно) и TransientProcessingError на таймаут/сетевую
    ошибку/5xx (auth_service временно недоступен — консьюмер сам решит,
    ретраить сейчас или поставить партицию на паузу, см. src/consumer.py).
    """
    url = f"{settings.auth_service_url}/internal/users/{user_id}"
    headers = (
        {"X-Internal-Api-Key": settings.auth_internal_api_key}
        if settings.auth_internal_api_key
        else {}
    )
    try:
        response = await _get_client().get(url, headers=headers)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
        raise TransientProcessingError(
            f"auth_service unreachable for user_id={user_id}: {exc}"
        ) from exc

    if response.status_code == 404:
        raise PermanentProcessingError(f"user_id={user_id} not found in auth_service")
    if response.status_code >= 500:
        raise TransientProcessingError(
            f"auth_service returned {response.status_code} for user_id={user_id}"
        )
    if response.status_code != 200:
        # Неожиданный код (401/403 — неверный/отсутствующий ключ и т.п.) —
        # это ошибка конфигурации воркера, не самого сообщения, но повторная
        # попытка того же запроса её не исправит без вмешательства человека;
        # трактуем как транзиентную, чтобы не терять уведомления молча, пока
        # это не увидят в логах/DLQ ретраев.
        raise TransientProcessingError(
            f"auth_service returned unexpected status {response.status_code} "
            f"for user_id={user_id}: {response.text}"
        )

    data = response.json()
    return UserProfile(
        id=uuid.UUID(data["id"]),
        email=data["email"],
        full_name=data.get("full_name") or "",
        is_active=data["is_active"],
    )
