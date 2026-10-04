"""Зависимости API: строгая JWT-аутентификация (без анонимного фолбэка) и
internal API key (docs/user_profiles_contract.md §1-2)."""

import secrets
import uuid

from fastapi import Header, HTTPException, Query, Request, status
from httpx import AsyncClient, HTTPError

from src.core.config import settings


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_token", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id(request: Request) -> uuid.UUID:
    """Авторизация self-service эндпоинтов (/me): по образцу
    ugc_service/src/api/dependencies.py:AuthServiceClient.get_current_user,
    но без анонимного фолбэка — любая проблема (нет заголовка, невалидный
    токен, auth_service недоступен) сразу 401."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise _unauthorized("Authorization header with Bearer token is required")
    token = auth_header.removeprefix("Bearer ").strip()

    try:
        async with AsyncClient(timeout=settings.auth_service_timeout) as client:
            response = await client.get(
                f"{settings.auth_service_url}/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
    except HTTPError as exc:
        raise _unauthorized("auth_service unavailable") from exc

    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        # auth_service/profile рейт-лимитирован (RATE_LIMIT_RELAXED) — это не
        # "токен невалиден", а наш пользователь слишком часто ходит в /me;
        # маскировать под 401 значило бы ложно сообщать, что сессия умерла.
        headers = {}
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            headers["Retry-After"] = retry_after
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "too_many_requests",
                "message": "Rate limited by auth_service",
            },
            headers=headers,
        )

    if response.status_code != 200:
        raise _unauthorized("Invalid or expired token")

    user_id = response.json().get("id")
    if not user_id:
        raise _unauthorized("Invalid auth_service response")

    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        raise _unauthorized("Invalid user id in auth_service response") from exc


async def verify_internal_api_key(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    """Авторизация S2S-вызовов (admin_panel, после T4 — auth_service) — копия
    auth_service/src/api/v1/dependencies.py:verify_internal_api_key. Пустой
    PROFILES_INTERNAL_API_KEY отключает проверку — для локальной разработки."""
    if not settings.internal_api_key:
        return
    if not x_internal_api_key or not secrets.compare_digest(
        x_internal_api_key, settings.internal_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_internal_api_key",
                "message": "Missing or invalid X-Internal-Api-Key",
            },
        )


class PaginationParams:
    """Параметры пагинации листинга профилей (контракт §2: page/page_size)."""

    def __init__(
        self,
        page: int = Query(default=1, ge=1, description="Номер страницы"),
        page_size: int = Query(
            default=20, ge=1, le=100, description="Элементов на странице"
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size
