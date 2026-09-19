"""Бизнес-логика рендер-стадии — обрабатывает одно сообщение
notifications.requests.v1: обогащает профилем из auth_service, проверяет
is_active и поддержку канала, рендерит шаблон, пишет
notification_contents/notifications/notification_log и публикует готовый
текст в notifications.ready.v1. См. план §5.1."""

import json
import logging
import uuid
from typing import Any, Optional

from aiokafka.structs import ConsumerRecord
from notification_schemas import NotificationKafkaMessage, to_ready_record
from pydantic import ValidationError

from src.clients.auth_client import get_user_profile
from src.core.errors import PermanentProcessingError
from src.db import queries
from src.db.postgres import get_pool
from src.kafka_producer import publish_ready
from src.templates.renderer import TemplateNotFoundError, get_template, render

logger = logging.getLogger(__name__)


def _safe_raw_message(raw_bytes: bytes) -> Optional[dict[str, Any]]:
    try:
        return {"raw_utf8": raw_bytes.decode("utf-8", errors="replace")[:4000]}
    except Exception:  # noqa: BLE001 — диагностический best-effort, не должен падать сам
        return None


def _try_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _record_skip(
    pool, message: NotificationKafkaMessage, *, reason: str
) -> None:
    """Терминальное состояние без отправки — пользователь неактивен или
    канал ещё не реализован. Content всё равно нужен: FK
    notifications.content_id NOT NULL REFERENCES notification_contents."""
    async with pool.acquire() as conn, conn.transaction():
        await queries.insert_content_and_notification(
            conn,
            notification_id=message.notification_id,
            template_pk=None,
            campaign_id=message.campaign_id,
            user_id=message.user_id,
            channel=message.channel,
            rendered_subject="",
            rendered_body="",
            status="skipped",
            scheduled_at=message.occurred_at,
        )
        await queries.insert_notification_history(
            conn, message.notification_id, "skipped", error_message=reason
        )
        await queries.update_notification_log_status(
            conn, message.notification_id, "skipped"
        )
    logger.info(f"notification_id={message.notification_id} skipped: {reason}")


async def handle_message(record: ConsumerRecord) -> None:
    pool = get_pool()

    try:
        raw = json.loads(record.value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        await queries.insert_dlq(
            pool,
            notification_id=None,
            stage="render",
            error_type="invalid_json",
            error_message=str(exc),
            raw_message=_safe_raw_message(record.value),
        )
        raise PermanentProcessingError(f"invalid JSON: {exc}") from exc

    try:
        message = NotificationKafkaMessage.model_validate(raw)
    except ValidationError as exc:
        maybe_id = raw.get("notification_id") if isinstance(raw, dict) else None
        await queries.insert_dlq(
            pool,
            notification_id=_try_uuid(maybe_id),
            stage="render",
            error_type="invalid_message",
            error_message=str(exc),
            raw_message=raw if isinstance(raw, dict) else None,
        )
        raise PermanentProcessingError(f"invalid message schema: {exc}") from exc

    # Идемпотентность/дедуп (план §5.1 п.2): любая уже существующая строка в
    # notifications означает, что это сообщение уже отрендерено в прошлом
    # проходе (redelivery до commit'а offset'а) — не рендерим повторно и не
    # публикуем повторно в ready-топик.
    existing_status = await queries.get_notification_status(pool, message.notification_id)
    if existing_status is not None:
        logger.info(
            f"notification_id={message.notification_id} already rendered "
            f"(status={existing_status}), skipping redelivery"
        )
        return

    try:
        profile = await get_user_profile(message.user_id)
    except PermanentProcessingError as exc:
        await queries.insert_dlq(
            pool,
            notification_id=message.notification_id,
            stage="render",
            error_type="user_not_found",
            error_message=str(exc),
            raw_message=message.model_dump(mode="json"),
        )
        await queries.update_notification_log_status(
            pool, message.notification_id, "render_failed"
        )
        raise

    if not profile.is_active:
        await _record_skip(pool, message, reason="user_inactive")
        return

    if message.channel != "email":
        # Только email реализован в этой итерации — sms/push оставляем
        # честно "skipped", а не вечным "pending" (план §5.1 п.5).
        await _record_skip(pool, message, reason="channel_not_implemented")
        return

    template_pk: Optional[int] = None
    if message.template_id:
        try:
            template = await get_template(message.template_id)
        except TemplateNotFoundError as exc:
            await queries.insert_dlq(
                pool,
                notification_id=message.notification_id,
                stage="render",
                error_type="template_not_found",
                error_message=str(exc),
                raw_message=message.model_dump(mode="json"),
            )
            await queries.update_notification_log_status(
                pool, message.notification_id, "render_failed"
            )
            raise PermanentProcessingError(str(exc)) from exc

        context = {
            **message.context,
            "user": {"name": profile.full_name, "email": profile.email},
        }
        rendered_subject, rendered_body = render(
            subject_template=template["subject"],
            body_template=template["body"],
            context=context,
        )
        subject = message.subject_override or rendered_subject
        body = message.text_override or rendered_body
        template_pk = int(message.template_id)
    else:
        subject = message.subject_override or ""
        body = message.text_override or ""

    async with pool.acquire() as conn, conn.transaction():
        await queries.insert_content_and_notification(
            conn,
            notification_id=message.notification_id,
            template_pk=template_pk,
            campaign_id=message.campaign_id,
            user_id=message.user_id,
            channel=message.channel,
            rendered_subject=subject,
            rendered_body=body,
            status="pending",
            scheduled_at=message.occurred_at,
        )
        await queries.update_notification_log_status(
            conn, message.notification_id, "queued_for_send"
        )

    ready_record = to_ready_record(
        message, recipient_email=profile.email, subject=subject, body=body
    )
    await publish_ready(key=str(message.user_id), value=ready_record)
    logger.info(f"notification_id={message.notification_id} rendered and queued for send")
