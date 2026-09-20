"""HTTP-клиент к internal-эндпоинту auth_service — проставляет
email_confirmed=True при первом валидном визите по ссылке
purpose=email_confirmation (auth_service/src/api/v1/internal.py).

По образцу notification_worker/src/clients/auth_client.py, но проще: здесь
нет партиций/ретраев Kafka-консьюмера, поэтому единственное, что нужно
вызывающему коду (src/services/link_service.py) — различить "подтверждено
или пользователь не найден, ссылку можно резолвить дальше" (см. §0.1
предварительного дизайна: не блокируем редирект, если сам пользователь уже
не существует) от "auth_service недоступен, редиректить нельзя, пока не
проставили флаг" (AuthServiceUnavailableError -> 503 на уровне роута)."""

import logging
import uuid

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


class AuthServiceUnavailableError(Exception):
    """Timeout/сетевая ошибка/5xx от auth_service — основной бизнес-эффект
    (подтверждение email) не подтверждён, редиректить пользователя нельзя."""


async def init_auth_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=settings.auth_service_timeout)
    logger.info("auth_service HTTP client ready: %s", settings.auth_service_url)


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


async def confirm_email(user_id: uuid.UUID) -> None:
    """Идемпотентный вызов auth_service. Возвращает None (успех) как на 204
    ("подтверждено"), так и на 404 ("пользователь не найден" — не блокируем
    резолв ссылки из-за уже несуществующего пользователя, только логируем).
    Поднимает AuthServiceUnavailableError на timeout/сетевую ошибку/5xx/любой
    другой неожиданный статус — вызывающий код не должен считать email
    подтверждённым и не должен редиректить."""
    url = f"{settings.auth_service_url}/internal/users/{user_id}/confirm-email"
    headers = (
        {"X-Internal-Api-Key": settings.auth_internal_api_key}
        if settings.auth_internal_api_key
        else {}
    )
    try:
        response = await _get_client().post(url, headers=headers)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
        raise AuthServiceUnavailableError(
            f"auth_service unreachable for user_id={user_id}: {exc}"
        ) from exc

    if response.status_code == 404:
        logger.warning(
            "user_id=%s not found in auth_service while confirming email; "
            "short link will still resolve",
            user_id,
        )
        return
    if response.status_code in (200, 204):
        return
    raise AuthServiceUnavailableError(
        f"auth_service returned unexpected status {response.status_code} "
        f"for user_id={user_id}: {response.text}"
    )
