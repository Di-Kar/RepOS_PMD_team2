"""Схема HTTP-заявки на уведомление и Kafka-сообщения после фан-аута —
контракт docs/notification_requests_contract.md.

С появлением notification_worker (S10_T3, issue #96) — второго потребителя
этого контракта — сама схема переехала в shared/notification_schemas.py (по
образцу shared/event_schemas.py для event_api/analytics_etl), чтобы не
разойтись между двумя сервисами, как когда-то разошлись event_api и
analytics_etl. Этот модуль остаётся тонкой точкой входа для остального кода
notification_api (импорты не пришлось переписывать) и добавляет проверку
NOTIFICATIONS_MAX_RECIPIENTS, специфичную для этого сервиса — shared-модуль
сознательно не знает про pydantic-settings конкретного потребителя.
"""

from notification_schemas import (  # noqa: F401
    NOTIFICATIONS_NAMESPACE,
    SCHEMA_VERSION,
    Channel,
    NotificationRequest as _NotificationRequest,
    derive_notification_id,
    to_kafka_record,
)
from pydantic import model_validator

from src.core.config import settings


class NotificationRequest(_NotificationRequest):
    """Расширяет общую схему проверкой лимита получателей — лимит настроен
    через NOTIFICATIONS_MAX_RECIPIENTS, переменную этого сервиса, поэтому
    живёт здесь, а не в shared/."""

    @model_validator(mode="after")
    def _limit_recipients(self) -> "NotificationRequest":
        if len(self.recipient_ids) > settings.max_recipients:
            raise ValueError(
                f"recipient_ids exceeds max size of {settings.max_recipients}"
            )
        return self


__all__ = [
    "NOTIFICATIONS_NAMESPACE",
    "SCHEMA_VERSION",
    "Channel",
    "NotificationRequest",
    "derive_notification_id",
    "to_kafka_record",
]
