"""Бизнес-логика рендер-стадии — обрабатывает одно сообщение
notifications.requests.v1: обогащает профилем из auth_service, проверяет
is_active и поддержку канала, рендерит шаблон, пишет
notification_contents/notifications/notification_log и публикует готовый
текст в notifications.ready.v1. См. план §5.1."""

import json
import logging
import uuid
from typing import Optional

from aiokafka.structs import ConsumerRecord
from notification_schemas import NotificationKafkaMessage, to_ready_record
from pydantic import ValidationError

from src.clients.auth_client import get_user_profile
from src.core.errors import PermanentProcessingError
from src.core.message_utils import safe_raw_message, try_uuid
from src.db import queries
from src.db.postgres import get_pool
from src.kafka_producer import publish_ready
from src.templates.renderer import (
    TemplateNotFoundError,
    TemplateRenderError,
    get_template,
    render,
)

logger = logging.getLogger(__name__)


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


async def _resume_pending(pool, message: NotificationKafkaMessage) -> None:
    """Дорабатывает сообщение, уже отрендеренное в предыдущей попытке,
    которая не успела опубликовать результат в notifications.ready.v1
    (например Kafka producer оборвался между DB-коммитом и publish_ready)
    — на redelivery notifications.status для него уже 'pending', а не
    None, поэтому обычная ветка идемпотентности приняла бы его за уже
    полностью обработанное и молча вышла, теряя уведомление навсегда
    (найдено ревью). Вместо повторного рендера публикуем уже сохранённый
    контент — republish в ready-топик безопасен благодаря идемпотентности
    send-стадии (§5.2): если он там уже обработан, send-стадия просто
    пропустит дубль по notification_id."""
    content = await queries.get_existing_rendered_content(pool, message.notification_id)
    if content is None:
        # Не должно происходить: FK гарантирует content_id для существующей
        # строки notifications. Но если всё же произошло — не ретраим
        # бесконечно, а честно фиксируем как постоянную ошибку.
        await queries.insert_dlq(
            pool,
            notification_id=message.notification_id,
            stage="render",
            error_type="content_missing_for_pending",
            error_message="notifications row is 'pending' but no matching notification_contents row",
            raw_message=message.model_dump(mode="json"),
        )
        raise PermanentProcessingError(
            f"notification_id={message.notification_id}: pending without content"
        )

    try:
        profile = await get_user_profile(message.user_id)
    except PermanentProcessingError as exc:
        # Пользователь пропал между первой и повторной попыткой — маловероятно,
        # но не блокируем партицию: фиксируем и завершаем.
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

    ready_record = to_ready_record(
        message,
        recipient_email=profile.email,
        subject=content["subject"],
        body=content["body"],
    )
    await publish_ready(key=str(message.user_id), value=ready_record)
    logger.info(
        f"notification_id={message.notification_id} republished to ready topic "
        "after incomplete previous attempt"
    )


async def handle_message(record: ConsumerRecord, attempt_id: uuid.UUID) -> None:
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
            raw_message=safe_raw_message(record.value),
        )
        raise PermanentProcessingError(f"invalid JSON: {exc}") from exc

    try:
        message = NotificationKafkaMessage.model_validate(raw)
    except ValidationError as exc:
        maybe_id = raw.get("notification_id") if isinstance(raw, dict) else None
        await queries.insert_dlq(
            pool,
            notification_id=try_uuid(maybe_id),
            stage="render",
            error_type="invalid_message",
            error_message=str(exc),
            raw_message=raw if isinstance(raw, dict) else None,
        )
        raise PermanentProcessingError(f"invalid message schema: {exc}") from exc

    logger.debug(f"notification_id={message.notification_id} attempt_id={attempt_id}")

    # Идемпотентность/дедуп (план §5.1 п.2): любая уже существующая строка в
    # notifications означает, что это сообщение уже обрабатывалось раньше.
    # 'pending' — особый случай: контент уже отрендерен, но неизвестно, был
    # ли он опубликован в ready-топик (см. _resume_pending) — остальные
    # статусы терминальны и означают, что делать больше нечего.
    existing_status = await queries.get_notification_status(pool, message.notification_id)
    if existing_status == "pending":
        await _resume_pending(pool, message)
        return
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
        try:
            rendered_subject, rendered_body = render(
                subject_template=template["subject"],
                body_template=template["body"],
                context=context,
            )
        except TemplateRenderError as exc:
            # Шаблон прошёл валидацию Django-синтаксиса в notification_admin_panel,
            # но не рендерится под Jinja2 (см. TemplateRenderError) — постоянная
            # ошибка самого шаблона, ретраить бессмысленно (найдено ревью:
            # раньше это исключение улетало необработанным и ретраилось вечно).
            await queries.insert_dlq(
                pool,
                notification_id=message.notification_id,
                stage="render",
                error_type="template_render_error",
                error_message=str(exc),
                raw_message=message.model_dump(mode="json"),
            )
            await queries.update_notification_log_status(
                pool, message.notification_id, "render_failed"
            )
            raise PermanentProcessingError(str(exc)) from exc
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
