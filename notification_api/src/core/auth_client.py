"""Проверка access-токена пользователя через auth_service (S10_T4, issue #97).

Локально JWT не расшифровываем — как и остальные сервисы проекта (async_api,
ugc_service): auth_service остаётся единственным источником истины о
валидности токена, logout виден сразу. В отличие от них здесь фейлимся
закрыто — websocket без резолвленного user_id не открываем вообще."""

import logging

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


async def resolve_user_id(token: str) -> str | None:
    """Возвращает user_id владельца токена или None (токен невалиден/истёк,
    auth_service недоступен)."""
    try:
        async with httpx.AsyncClient(timeout=settings.auth_service_timeout) as client:
            response = await client.get(
                f"{settings.auth_service_url}/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        logger.warning(f"auth_service unreachable while resolving websocket token: {exc}")
        return None

    if response.status_code != 200:
        return None
    return response.json().get("id")
