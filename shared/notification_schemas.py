"""Единый источник схем сообщений по границе notification_api <->
notification_worker — контракт docs/notification_requests_contract.md.

Модуль общий для notification_api (продюсер `notifications.requests.v1`,
консьюмер §9 статусов в notification_log) и notification_worker (консьюмер
`notifications.requests.v1`, продюсер `notifications.ready.v1`). Раньше
схема HTTP-заявки и Kafka-сообщения жила только в
`notification_api/src/models/schemas.py` — комментарий в том файле прямо
указывал перенести её сюда, как только у контракта появится второй
потребитель (по аналогии с shared/event_schemas.py для event_api/analytics_etl).

Модуль намеренно не знает про pydantic-settings конкретного сервиса
(`src.core.config`) — лимит `NOTIFICATIONS_MAX_RECIPIENTS` проверяется
вызывающим сервисом (notification_api) отдельно, после парсинга этой модели,
а не встроен в валидатор: shared-код не должен зависеть от settings одного
конкретного потребителя.
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

Channel = Literal["email", "sms", "push", "websocket"]

# Namespace для детерминированного notification_id (контракт §6) — фиксирован
# и не должен меняться, иначе повторная отправка того же request_id перестанет
# давать те же notification_id, а уже обработанные воркером уведомления
# перестанут находиться по старому notification_id.
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


def derive_notification_id(request_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """Детерминированный notification_id (контракт §6) — повтор того же
    request_id при ретрае клиента даёт те же notification_id, дедуп по факту
    доставки остаётся возможным ниже по потоку (у notification_worker)."""
    return uuid.uuid5(NOTIFICATIONS_NAMESPACE, f"{request_id}:{user_id}")


def to_kafka_record(
    request: NotificationRequest,
    user_id: uuid.UUID,
    received_at: datetime | None = None,
) -> dict:
    """Сериализует одно (после фан-аута) уведомление в JSON-совместимый dict
    для value сообщения `notifications.requests.v1` (контракт §4).
    received_at по умолчанию — момент вызова; принимает готовое значение,
    чтобы вызывающий (запись лога в БД, §9) использовал ровно тот же
    timestamp, что ушёл в Kafka."""
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


class NotificationKafkaMessage(BaseModel):
    """Value сообщения `notifications.requests.v1` (контракт §4), после
    фан-аута — один получатель. Валидируется notification_worker при чтении:
    сообщение, не проходящее эту схему, считается поломанным (DLQ
    немедленно, без ретраев), в отличие от бизнес-ошибок (профиль не найден,
    шаблон не найден и т.п.), которые проходят парсинг успешно."""

    model_config = ConfigDict(extra="ignore")

    notification_id: uuid.UUID
    request_id: uuid.UUID
    schema_version: int
    source_service: str
    campaign_id: str | None = None
    user_id: uuid.UUID
    channel: Channel
    template_id: str | None = None
    subject_override: str | None = None
    text_override: str | None = None
    context: dict = Field(default_factory=dict)
    occurred_at: datetime
    received_at: datetime

    @model_validator(mode="after")
    def _require_content_source(self) -> "NotificationKafkaMessage":
        if not self.template_id and not self.text_override:
            raise ValueError("either template_id or text_override is required")
        return self


class ReadyToSendMessage(BaseModel):
    """Value сообщения `notifications.ready.v1` — выход
    notification_worker_render, вход отправляющих воркеров (email/sms/push).
    Уже несёт отрендеренный контент и контактные данные получателя (email),
    полученные рендер-стадией из auth_service — send-стадия auth_service
    повторно не вызывает."""

    model_config = ConfigDict(extra="ignore")

    notification_id: uuid.UUID
    request_id: uuid.UUID
    schema_version: int
    source_service: str
    campaign_id: str | None = None
    user_id: uuid.UUID
    channel: Channel
    recipient_email: str | None = None
    subject: str
    body: str
    context: dict = Field(default_factory=dict)
    occurred_at: datetime
    received_at: datetime
    rendered_at: datetime


def to_ready_record(
    message: NotificationKafkaMessage,
    *,
    recipient_email: str | None,
    subject: str,
    body: str,
    rendered_at: datetime | None = None,
) -> dict:
    """Сериализует результат рендера в JSON-совместимый dict для value
    сообщения `notifications.ready.v1`."""
    return {
        "notification_id": str(message.notification_id),
        "request_id": str(message.request_id),
        "schema_version": message.schema_version,
        "source_service": message.source_service,
        "campaign_id": message.campaign_id,
        "user_id": str(message.user_id),
        "channel": message.channel,
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "context": message.context,
        "occurred_at": message.occurred_at.isoformat(),
        "received_at": message.received_at.isoformat(),
        "rendered_at": (rendered_at or datetime.now(timezone.utc)).isoformat(),
    }
