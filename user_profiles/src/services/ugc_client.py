"""S2S-клиент к ugc_service для агрегирующей витрины профиля (S11_T6, GET
/api/v1/profiles/{user_id}/full). При любой проблеме с ugc_service
(недоступность, таймаут, не-200, невалидное тело) возвращает None — вызывающий код
деградирует к профилю без UGC-данных вместо 500, по аналогии с
async_api/src/db/auth_client.py."""

import logging
import uuid

from httpx import AsyncClient, HTTPError
from pydantic import ValidationError

from src.core.config import settings
from src.models.schemas import UgcSummary

logger = logging.getLogger(__name__)


async def get_user_ugc_summary(user_id: uuid.UUID) -> UgcSummary | None:
    try:
        async with AsyncClient(timeout=settings.ugc_service_timeout) as client:
            response = await client.get(
                f"{settings.ugc_service_url}/api/v1/internal/users/{user_id}/ugc-summary",
                headers={"X-Internal-Api-Key": settings.ugc_internal_api_key},
            )
        if response.status_code != 200:
            logger.warning(
                "ugc_service вернул %s для user_id=%s", response.status_code, user_id
            )
            return None
        return UgcSummary.model_validate(response.json())
    except (HTTPError, ValueError, ValidationError) as exc:
        # ValueError — response.json() на не-JSON/битом теле; ValidationError —
        # тело не соответствует схеме UgcSummary (не объект, null вместо
        # списка, элемент без обязательных полей). Все случаи — тот же
        # "ugc_service недоступен/отдал мусор", что и сетевая ошибка (в т.ч.
        # при ответе 200 от неисправного прокси перед ugc_service).
        logger.warning("ugc_service недоступен или вернул некорректный ответ: %s", exc)
        return None
