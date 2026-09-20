"""Best-effort клиент к link_shortener_service: создаёт короткую ссылку
подтверждения email для welcome-письма.

По образцу src/services/notification_client.py — недоступность
link_shortener_service не должна ронять /register: любая ошибка логируется
как warning и превращается в None, вызывающий код (src/services/
registration_notifications.py) сам решает, как деградировать."""

import logging
import uuid

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


async def create_email_confirmation_link(user_id: uuid.UUID) -> str | None:
    """Возвращает короткую ссылку подтверждения email или None при любой
    ошибке/недоступности link_shortener_service."""
    payload = {
        "source_service": "auth_service",
        "owner_user_id": str(user_id),
        "purpose": "email_confirmation",
        "redirect_url": settings.email_confirm_redirect_url,
        "ttl_seconds": settings.email_confirm_link_ttl_seconds,
    }
    headers = (
        {"X-API-Key": settings.links_api_key} if settings.links_api_key else {}
    )
    try:
        async with httpx.AsyncClient(timeout=settings.links_api_timeout) as client:
            response = await client.post(
                f"{settings.links_api_url}/links",
                json=payload,
                headers=headers,
            )
        if response.status_code != 201:
            logger.warning(
                "link_shortener_service returned unexpected status %s: %s",
                response.status_code,
                response.text,
            )
            return None
        return response.json()["short_url"]
    except httpx.HTTPError as exc:
        logger.warning("link_shortener_service unreachable: %s", exc)
        return None
    except (KeyError, ValueError) as exc:
        logger.warning("link_shortener_service returned unexpected body: %s", exc)
        return None
