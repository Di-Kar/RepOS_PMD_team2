"""Best-effort уведомления через notification_api (S10_T7, issue #100):
приветственное письмо при регистрации, оповещение о смене пароля.

Заявка в свободном формате (text_override, без template_id) — по образцу
docs/notification_requests_contract.md §7. Отправка выполняется в фоновой
задаче (см. вызовы в src/api/v1/auth.py): недоступность notification_api не
должна ронять сам auth-эндпоинт, это побочный эффект, а не часть транзакции.
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


async def _send_notification(
    *, recipient_id: uuid.UUID, subject: str, text: str
) -> None:
    payload = {
        "request_id": str(uuid.uuid4()),
        "source_service": "auth_service",
        "channel": "email",
        "subject_override": subject,
        "text_override": text,
        "context": {},
        "recipient_ids": [str(recipient_id)],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    headers = (
        {"X-API-Key": settings.notifications_api_key}
        if settings.notifications_api_key
        else {}
    )
    try:
        async with httpx.AsyncClient(
            timeout=settings.notifications_api_timeout
        ) as client:
            response = await client.post(
                f"{settings.notifications_api_url}/notifications",
                json=payload,
                headers=headers,
            )
        if response.status_code != 202:
            logger.warning(
                "notification_api returned unexpected status %s: %s",
                response.status_code,
                response.text,
            )
    except httpx.HTTPError as exc:
        logger.warning("notification_api unreachable: %s", exc)


async def send_welcome_notification(user_id: uuid.UUID) -> None:
    await _send_notification(
        recipient_id=user_id,
        subject="Регистрация завершена",
        text="Добро пожаловать! Ваш аккаунт создан.",
    )


async def send_password_changed_notification(user_id: uuid.UUID) -> None:
    await _send_notification(
        recipient_id=user_id,
        subject="Пароль изменён",
        text=(
            "Пароль вашего аккаунта был изменён. Если это были не вы — "
            "срочно смените пароль ещё раз и завершите все сессии."
        ),
    )
