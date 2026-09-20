"""Зависимости роутов link_shortener_service."""

import secrets

from fastapi import Header, HTTPException, status

from src.core.config import settings


async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Авторизация вызывающих сервисов POST /api/v1/links (docs/
    link_shortener_contract.md §1). Пустой LINKS_API_KEY отключает проверку —
    для локальной разработки. GET /r/{code} этой зависимостью не защищён —
    он публичный по конструкции (см. §5 контракта)."""
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
