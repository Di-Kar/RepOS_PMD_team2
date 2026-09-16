"""
HTTP-клиент для notification_api (S10_T1).
Отправляет заявки на создание уведомлений.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class NotificationApiResult:
    """Результат отправки заявки в notification_api."""

    request_id: uuid.UUID
    status: str  # accepted / partially_accepted / rejected
    accepted_count: int
    rejected_recipients: list[dict]  # [{"user_id": "...", "reason": "..."}]
    errors: list[str]  # Ошибки валидации заявки целиком

    @property
    def is_success(self) -> bool:
        return self.accepted_count > 0


class NotificationApiClient:
    """
    Клиент для notification_api.
    Stateless, не имеет собственной БД.
    """

    def __init__(self):
        self.base_url = settings.NOTIFICATION_API_URL.rstrip("/")
        self.api_key = settings.NOTIFICATION_API_KEY
        self.timeout = settings.NOTIFICATION_API_TIMEOUT

    def send_notification_request(
        self,
        channel: str,
        recipient_ids: list[str],
        occurred_at: str,
        template_id: Optional[str] = None,
        text_override: Optional[str] = None,
        subject_override: Optional[str] = None,
        context: Optional[dict] = None,
        campaign_id: Optional[str] = None,
        request_id: Optional[uuid.UUID] = None,  # ИЗМЕНЕНО: UUID
    ) -> NotificationApiResult:
        """
        Отправляет заявку на создание уведомлений.
        Args:
            channel: Канал доставки (email/sms/push)
            recipient_ids: Список UUID получателей
            occurred_at: Когда произошло событие (ISO 8601)
            template_id: ID шаблона (если используется шаблон)
            text_override: Готовый текст (если без шаблона)
            subject_override: Переопределение темы (для email)
            context: Доп. переменные для рендера шаблона
            campaign_id: ID кампании в admin_panel (опционально)
            request_id: ID заявки (для идемпотентности, генерируется автоматически)

        Returns:
            NotificationApiResult с результатом отправки
        """
        if request_id is None:
            request_id = uuid.uuid4()

        payload = {
            "request_id": str(request_id),  # Конвертируем в строку для JSON
            "source_service": settings.NOTIFICATION_SOURCE_SERVICE,
            "channel": channel,
            "recipient_ids": recipient_ids,
            "occurred_at": occurred_at,
        }

        if campaign_id:
            payload["campaign_id"] = str(campaign_id)
        if template_id:
            payload["template_id"] = str(template_id)
        if text_override:
            payload["text_override"] = text_override
        if subject_override:
            payload["subject_override"] = subject_override
        if context:
            payload["context"] = context

        url = f"{self.base_url}/notifications"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )

            if response.status_code != 202:
                logger.error(
                    "notification_api returned unexpected status %s: %s",
                    response.status_code,
                    response.text,
                )
                return NotificationApiResult(
                    request_id=request_id,
                    status="rejected",
                    accepted_count=0,
                    rejected_recipients=[],
                    errors=[f"HTTP {response.status_code}: {response.text}"],
                )

            data = response.json()

            returned_request_id = data["request_id"]
            if isinstance(returned_request_id, str):
                returned_request_id = uuid.UUID(returned_request_id)

            return NotificationApiResult(
                request_id=returned_request_id,
                status=data["status"],
                accepted_count=data["accepted_count"],
                rejected_recipients=data.get("rejected_recipients", []),
                errors=data.get("errors", []),
            )

        except requests.exceptions.Timeout:
            logger.error("notification_api timeout for request_id=%s", request_id)
            return NotificationApiResult(
                request_id=request_id,
                status="rejected",
                accepted_count=0,
                rejected_recipients=[],
                errors=["Timeout connecting to notification_api"],
            )
        except requests.exceptions.RequestException as exc:
            logger.error("notification_api error: %s", exc)
            return NotificationApiResult(
                request_id=request_id,
                status="rejected",
                accepted_count=0,
                rejected_recipients=[],
                errors=[f"Connection error: {exc}"],
            )


# Singleton для переиспользования
_client = None


def get_notification_api_client() -> NotificationApiClient:
    global _client
    if _client is None:
        _client = NotificationApiClient()
    return _client
