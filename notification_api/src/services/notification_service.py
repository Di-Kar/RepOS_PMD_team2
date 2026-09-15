"""Валидация заявки, фан-аут по получателям и публикация в Kafka
(docs/notification_requests_contract.md §1, §5, §6)."""

import asyncio
import logging
import uuid

from pydantic import TypeAdapter, ValidationError

from src.core.kafka_producer import publish_notification
from src.models.responses import NotificationRequestResult, RejectedRecipient
from src.models.schemas import NotificationRequest, to_kafka_record

logger = logging.getLogger(__name__)

_request_adapter: TypeAdapter = TypeAdapter(NotificationRequest)


def _split_recipients(
    raw_recipient_ids: list[str],
) -> tuple[list[uuid.UUID], list[RejectedRecipient]]:
    """Разбирает recipient_ids на валидные UUID (без дублей, порядок
    сохранён) и отклонённых по отдельности — невалидный UUID у одного
    получателя не блокирует остальных (§5 контракта)."""
    valid: dict[uuid.UUID, None] = {}
    rejected: list[RejectedRecipient] = []
    for raw_uid in raw_recipient_ids:
        try:
            valid[uuid.UUID(raw_uid)] = None
        except (ValueError, AttributeError, TypeError):
            rejected.append(
                RejectedRecipient(user_id=str(raw_uid), reason="invalid_uuid")
            )
    return list(valid.keys()), rejected


async def _publish_one(
    request: NotificationRequest, user_id: uuid.UUID
) -> RejectedRecipient | None:
    """Публикует одно уведомление; возвращает причину отказа или None при успехе."""
    record = to_kafka_record(request, user_id)
    try:
        await publish_notification(key=str(user_id), value=record)
    except Exception as exc:
        logger.error(
            f"Failed to publish notification {record['notification_id']} "
            f"(request {request.request_id}) to Kafka: {exc}"
        )
        return RejectedRecipient(user_id=str(user_id), reason="kafka_publish_failed")
    return None


async def process_notification_request(raw: dict) -> NotificationRequestResult:
    """Валидирует заявку (§5) и публикует в Kafka по одному сообщению на
    получателя (§1, фан-аут). Невалидная заявка целиком не роняет остальные
    заявки batch'а — помечается status="rejected", HTTP всегда 202 (§2)."""
    try:
        request = _request_adapter.validate_python(raw)
    except ValidationError as exc:
        request_id = raw.get("request_id") if isinstance(raw, dict) else None
        errors = [
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return NotificationRequestResult(
            request_id=str(request_id) if request_id else None,
            status="rejected",
            errors=errors,
        )

    valid_recipients, rejected = _split_recipients(request.recipient_ids)

    if not valid_recipients:
        return NotificationRequestResult(
            request_id=str(request.request_id),
            status="rejected",
            accepted_count=0,
            rejected_recipients=rejected,
        )

    publish_results = await asyncio.gather(
        *(_publish_one(request, user_id) for user_id in valid_recipients)
    )
    rejected.extend(reason for reason in publish_results if reason is not None)
    accepted_count = len(valid_recipients) - sum(
        1 for reason in publish_results if reason is not None
    )

    if not rejected:
        status = "accepted"
    elif accepted_count > 0:
        status = "partially_accepted"
    else:
        status = "rejected"

    return NotificationRequestResult(
        request_id=str(request.request_id),
        status=status,
        accepted_count=accepted_count,
        rejected_recipients=rejected,
    )
