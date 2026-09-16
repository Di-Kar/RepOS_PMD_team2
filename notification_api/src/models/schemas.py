"""Схема HTTP-заявки на уведомление и Kafka-сообщения после фан-аута —
контракт docs/notification_requests_contract.md.

Пока это единственный сервис, работающий с этой схемой (notification_worker
из S10_T3 ещё не существует в репозитории) — модуль живёт в notification_api,
а не в shared/, как shared/event_schemas.py для event_api/analytics_etl.
Если воркер появится в этом репозитории, схему стоит вынести в shared/, чтобы
не расходиться, как когда-то разошлись event_api и analytics_etl."""

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.config import settings

SCHEMA_VERSION = 1

Channel = Literal["email", "sms", "push", "websocket"]

# Namespace для детерминированного notification_id (контракт §6) — фиксирован
# и не должен меняться, иначе повторная отправка того же request_id перестанет
# давать те же notification_id.
NOTIFICATIONS_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS, "notification-api.repospmd.local"
)


class NotificationRequest(BaseModel):
    """HTTP-заявка (контракт §3), до фан-аута по получателям.

    recipient_ids намеренно типизирован как list[str], а не list[UUID]:
    невалидный UUID у одного получателя не должен ронять валидацию всей
    заявки (§5 контракта) — по одному элементу разбираем сами в сервисе.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    source_service: str = Field(min_length=1)
    campaign_id: str | None = None
    channel: Channel
    template_id: str | None = None
    subject_override: str | None = None
    text_override: str | None = None
    context: dict = Field(default_factory=dict)
    recipient_ids: list[str] = Field(min_length=1)
    occurred_at: datetime

    @model_validator(mode="after")
    def _require_content_source(self) -> "NotificationRequest":
        if not self.template_id and not self.text_override:
            raise ValueError("either template_id or text_override is required")
        return self

    @model_validator(mode="after")
    def _limit_recipients(self) -> "NotificationRequest":
        if len(self.recipient_ids) > settings.max_recipients:
            raise ValueError(
                f"recipient_ids exceeds max size of {settings.max_recipients}"
            )
        return self


def derive_notification_id(request_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """Детерминированный notification_id (контракт §6) — повтор того же
    request_id при ретрае клиента даёт те же notification_id, без своей БД у
    notification_api дедуп остаётся возможным ниже по потоку (у воркера)."""
    return uuid.uuid5(NOTIFICATIONS_NAMESPACE, f"{request_id}:{user_id}")


def to_kafka_record(
    request: NotificationRequest,
    user_id: uuid.UUID,
    received_at: datetime | None = None,
) -> dict:
    """Сериализует одно (после фан-аута) уведомление в JSON-совместимый dict
    для value сообщения Kafka (контракт §4). received_at по умолчанию — момент
    вызова; принимает готовое значение, чтобы вызывающий (запись лога в БД,
    §9) использовал ровно тот же timestamp, что ушёл в Kafka."""
    return {
        "notification_id": str(derive_notification_id(request.request_id, user_id)),
        "request_id": str(request.request_id),
        "schema_version": SCHEMA_VERSION,
        "source_service": request.source_service,
        "campaign_id": request.campaign_id,
        "user_id": str(user_id),
        "channel": request.channel,
        "template_id": request.template_id,
        "subject_override": request.subject_override,
        "text_override": request.text_override,
        "context": request.context,
        "occurred_at": request.occurred_at.isoformat(),
        "received_at": (received_at or datetime.now(timezone.utc)).isoformat(),
    }
