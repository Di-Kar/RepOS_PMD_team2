"""Зависимости роутов event_api."""

import secrets

from fastapi import Header, HTTPException, status

from src.core.config import settings


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Авторизация клиентской части (NFR-20). Пустой EVENTS_API_KEY отключает
    проверку — для локальной разработки."""
    if not settings.api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "invalid_api_key",
                "message": "Missing or invalid X-API-Key",
            },
        )
