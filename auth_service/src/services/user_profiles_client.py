import logging
import uuid
from typing import Optional

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)

async def get_user_profile(user_id: uuid.UUID) -> Optional[dict]:
    """Забирает профиль пользователя из user_profiles по internal API."""
    headers = (
        {"X-Internal-Api-Key": settings.internal_api_key}
        if settings.internal_api_key else {}
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.user_profiles_api_url}/profiles/{user_id}",
                headers=headers,
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning("user_profiles_service unreachable for user %s: %s", user_id, exc)
        return None
    except ValueError as exc:
        logger.warning("user_profiles_service returned unexpected body for user %s: %s", user_id, exc)
        return None
