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

    # ИСПРАВЛЕНИЕ #5: Флаг для логики повторных попыток (retry)
    is_temporary_error: bool = False

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
        self.timeout = getattr(settings, "NOTIFICATION_API_TIMEOUT", 10)

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
        request_id: Optional[uuid.UUID] = None,
    ) -> NotificationApiResult:
        """
        Отправляет заявку на создание уведомлений.
        """
        if request_id is None:
            request_id = uuid.uuid4()

        payload = {
            "request_id": str(request_id),
            "source_service": getattr(
                settings, "NOTIFICATION_SOURCE_SERVICE", "admin_panel"
            ),
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

        url = f"{self.base_url}/api/v1/notifications"

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )

            # Успешный приём заявки брокером/API
            if response.status_code == 202:
                data = response.json()
                returned_request_id = data.get("request_id", str(request_id))
                if isinstance(returned_request_id, str):
                    returned_request_id = uuid.UUID(returned_request_id)

                return NotificationApiResult(
                    request_id=returned_request_id,
                    status=data.get("status", "rejected"),
                    accepted_count=data.get("accepted_count", 0),
                    rejected_recipients=data.get("rejected_recipients", []),
                    errors=data.get("errors", []),
                    is_temporary_error=False,
                )

            is_temporary = response.status_code >= 500

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
                errors=[f"HTTP {response.status_code}: {response.text.strip()}"],
                is_temporary_error=is_temporary,
            )

        except requests.exceptions.Timeout:
            logger.warning("notification_api timeout for request_id=%s", request_id)
            return NotificationApiResult(
                request_id=request_id,
                status="rejected",
                accepted_count=0,
                rejected_recipients=[],
                errors=["Timeout connecting to notification_api"],
                is_temporary_error=True,  # Таймаут — классическая временная ошибка
            )

        except requests.exceptions.ConnectionError:
            logger.warning(
                "notification_api connection error for request_id=%s", request_id
            )
            return NotificationApiResult(
                request_id=request_id,
                status="rejected",
                accepted_count=0,
                rejected_recipients=[],
                errors=["Connection error to notification_api"],
                is_temporary_error=True,  # Обрыв сети — временная ошибка
            )

        except requests.exceptions.RequestException as exc:
            logger.error("notification_api unexpected request error: %s", exc)
            return NotificationApiResult(
                request_id=request_id,
                status="rejected",
                accepted_count=0,
                rejected_recipients=[],
                errors=[f"Unexpected request error: {exc}"],
                is_temporary_error=True,  # На всякий случай помечаем как временную для retry
            )


# Singleton для переиспользования
_client = None


def get_notification_api_client() -> NotificationApiClient:
    global _client
    if _client is None:
        _client = NotificationApiClient()
    return _client
