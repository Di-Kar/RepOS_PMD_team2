"""Валидация заявки, фан-аут по получателям, публикация в Kafka и запись
лога отправленных заявок (docs/notification_requests_contract.md §1, §5, §6, §9)."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.core.kafka_producer import publish_notification
from src.db.postgres import AsyncSessionLocal
from src.models.entity import (
    STATUS_KAFKA_PUBLISH_FAILED,
    STATUS_KAFKA_PUBLISHED,
    NotificationLog,
)
from src.models.responses import NotificationRequestResult, RejectedRecipient
from src.models.schemas import (
    NotificationRequest,
    derive_notification_id,
    to_kafka_record,
)

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
) -> tuple[dict, RejectedRecipient | None]:
    """Публикует одно уведомление; возвращает значения строки лога для БД
    (§9, статус проставлен по результату публикации) и причину отказа либо
    None при успехе."""
    received_at = datetime.now(timezone.utc)
    record = to_kafka_record(request, user_id, received_at=received_at)
    log_row = {
        "notification_id": derive_notification_id(request.request_id, user_id),
        "request_id": request.request_id,
        "schema_version": record["schema_version"],
        "source_service": request.source_service,
        "campaign_id": request.campaign_id,
        "user_id": user_id,
        "channel": request.channel,
        "template_id": request.template_id,
        "subject_override": request.subject_override,
        "text_override": request.text_override,
        "context": request.context,
        "occurred_at": request.occurred_at,
        "received_at": received_at,
    }
    try:
        await publish_notification(key=str(user_id), value=record)
    except Exception as exc:
        logger.error(
            f"Failed to publish notification {record['notification_id']} "
            f"(request {request.request_id}) to Kafka: {exc}"
        )
        log_row["status"] = STATUS_KAFKA_PUBLISH_FAILED
        return log_row, RejectedRecipient(
            user_id=str(user_id), reason="kafka_publish_failed"
        )
    log_row["status"] = STATUS_KAFKA_PUBLISHED
    return log_row, None


# Поля заявки, которые обновляем при повторной публикации той же заявки (тот
# же notification_id, §6) — ретрай может нести то же содержимое или превратить
# прошлый kafka_publish_failed в успех.
_UPSERT_UPDATE_COLUMNS = (
    "schema_version",
    "source_service",
    "campaign_id",
    "channel",
    "template_id",
    "subject_override",
    "text_override",
    "context",
    "occurred_at",
    "received_at",
)

# status — особый случай: если notification_worker уже успел обновить его
# (значит сообщение реально дошло до консьюмера), ретрай публикации не должен
# отбрасывать этот статус назад в kafka_published/kafka_publish_failed —
# перезаписываем status только пока он ещё "наш" (см. entity.py).
_OWN_STATUSES = (STATUS_KAFKA_PUBLISHED, STATUS_KAFKA_PUBLISH_FAILED)


async def _persist_log_entries(rows: list[dict]) -> None:
    """Пишет лог заявок в БД одним batch'ем (§9), upsert по notification_id —
    ретрай того же request_id даёт тот же notification_id (§6) и должен
    обновить строку, а не упасть на конфликте PK. Best-effort: сбой записи в
    БД не должен ронять уже отправленный клиенту ответ и не откатывает
    публикацию в Kafka — источником истины остаётся Kafka, БД лишь даёт
    notification_worker посадочную площадку для статусов."""
    if not rows:
        return
    try:
        async with AsyncSessionLocal() as session:
            stmt = pg_insert(NotificationLog).values(rows)
            update_values = {
                col: getattr(stmt.excluded, col) for col in _UPSERT_UPDATE_COLUMNS
            }
            update_values["status"] = case(
                (NotificationLog.status.in_(_OWN_STATUSES), stmt.excluded.status),
                else_=NotificationLog.status,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[NotificationLog.notification_id],
                set_=update_values,
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.error(f"Failed to persist notification log entries to DB: {exc}")


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
    log_rows = [log_row for log_row, _ in publish_results]
    publish_rejections = [reason for _, reason in publish_results if reason is not None]
    rejected.extend(publish_rejections)
    accepted_count = len(valid_recipients) - len(publish_rejections)

    await _persist_log_entries(log_rows)

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
