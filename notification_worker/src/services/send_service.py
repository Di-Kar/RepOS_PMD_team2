"""Бизнес-логика send-стадии (email) — обрабатывает одно сообщение
notifications.ready.v1: идемпотентно отправляет письмо (проверяет текущий
статус перед отправкой — redelivery/ретрай не должен дублировать письмо),
пишет notification_history и обновляет notifications/notification_log. См.
план §5.2."""

import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg
from aiokafka.structs import ConsumerRecord
from notification_schemas import ReadyToSendMessage
from pydantic import ValidationError

from src.clients.email_client import PermanentSendError, send_email
from src.core.errors import PermanentProcessingError
from src.core.message_utils import safe_raw_message, try_uuid
from src.db import queries
from src.db.postgres import get_pool

logger = logging.getLogger(__name__)


async def _claim_for_sending(
    pool: asyncpg.Pool, message: ReadyToSendMessage, attempt_id: uuid.UUID
) -> bool:
    """Возвращает True, если можно (продолжать) слать письмо, False —
    сообщение уже обработано/не подлежит обработке (никаких дальнейших
    действий не требуется).

    Разбор статуса 'sending' — ключевая часть идемпотентности. Kafka
    гарантирует, что одну и ту же партицию (а значит, и notification_id —
    партиционирование по user_id) в любой момент читает не больше одного
    консьюмера в группе — но нужно ещё отличить "это моя же, ещё не
    прервавшаяся серия ретраев ЭТОГО ЖЕ сообщения" (consumer.py,
    TransientProcessingError) от "предыдущий вызов упал после claim'а, но
    до/после фактической отправки" (перезапуск процесса, переигровка
    offset'а). Раньше это решалось эвристикой по времени
    (NOTIFICATION_WORKER_SEND_LEASE_SECONDS) — она не могла надёжно
    различить свежий чужой crash от своего же живого ретрая (см. ревью).
    Теперь `attempt_id` — случайный, стабильный только в пределах одного
    непрерывного вызова consumer.py._process_with_retry на это сообщение
    (src/consumer.py) — записывается вместе со статусом 'sending' и
    сверяется точным сравнением, без угадывания по времени."""
    async with pool.acquire() as conn, conn.transaction():
        status = await queries.get_status_for_claim(conn, message.notification_id)
        if status is None:
            # Render-стадия обязана создать эту строку до публикации в
            # ready-топик — отсутствие означает рассинхрон, а не штатный
            # случай; разбираем отдельно, не пытаясь угадать контент.
            await queries.insert_dlq(
                conn,
                notification_id=message.notification_id,
                stage="send",
                error_type="notification_row_missing",
                error_message="no notifications row for ready message",
                raw_message=message.model_dump(mode="json"),
            )
            return False

        if status in ("sent", "failed", "skipped"):
            logger.info(
                f"notification_id={message.notification_id} already {status}, "
                "skipping redelivery"
            )
            return False

        if status == "sending":
            current_attempt = await queries.get_latest_sending_attempt(
                conn, message.notification_id
            )
            if current_attempt == str(attempt_id):
                # Точно та же, ещё не прервавшаяся серия ретраев этого же
                # процесса на это же сообщение — безопасно продолжать.
                return True
            await queries.insert_dlq(
                conn,
                notification_id=message.notification_id,
                stage="send",
                error_type="send_ambiguous",
                error_message=(
                    f"stuck in 'sending' under a different attempt_id "
                    f"({current_attempt!r} != {attempt_id}) — process likely "
                    "crashed after claiming; not auto-retrying to avoid "
                    "duplicate delivery"
                ),
                raw_message=message.model_dump(mode="json"),
            )
            await queries.update_notification_log_status(
                conn, message.notification_id, "requires_manual_review"
            )
            return False

        # status == "pending"
        await queries.mark_sending(conn, message.notification_id, attempt_id)
        return True


async def _record_result(
    pool: asyncpg.Pool,
    message: ReadyToSendMessage,
    *,
    status: str,
    error_message: str = "",
) -> None:
    sent_at = datetime.now(timezone.utc) if status == "sent" else None
    async with pool.acquire() as conn, conn.transaction():
        await queries.update_notification_status(
            conn, message.notification_id, status, sent_at=sent_at
        )
        await queries.insert_notification_history(
            conn,
            message.notification_id,
            status,
            error_message=error_message,
            delivery_provider="smtp",
        )
        await queries.update_notification_log_status(conn, message.notification_id, status)


async def handle_message(record: ConsumerRecord, attempt_id: uuid.UUID) -> None:
    pool = get_pool()

    try:
        raw = json.loads(record.value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        await queries.insert_dlq(
            pool,
            notification_id=None,
            stage="send",
            error_type="invalid_json",
            error_message=str(exc),
            raw_message=safe_raw_message(record.value),
        )
        raise PermanentProcessingError(f"invalid JSON: {exc}") from exc

    try:
        message = ReadyToSendMessage.model_validate(raw)
    except ValidationError as exc:
        maybe_id = raw.get("notification_id") if isinstance(raw, dict) else None
        await queries.insert_dlq(
            pool,
            notification_id=try_uuid(maybe_id),
            stage="send",
            error_type="invalid_message",
            error_message=str(exc),
            raw_message=raw if isinstance(raw, dict) else None,
        )
        raise PermanentProcessingError(f"invalid message schema: {exc}") from exc

    if message.channel != "email":
        # Другой канал — ждёт своего sender'а (sms/push, пока не
        # реализованы), этот процесс не трогает сообщение вовсе.
        return

    if not await _claim_for_sending(pool, message, attempt_id):
        return

    try:
        await send_email(to=message.recipient_email, subject=message.subject, body=message.body)
    except PermanentSendError as exc:
        await _record_result(pool, message, status="failed", error_message=str(exc))
        await queries.insert_dlq(
            pool,
            notification_id=message.notification_id,
            stage="send",
            error_type="smtp_permanent",
            error_message=str(exc),
            raw_message=message.model_dump(mode="json"),
        )
        raise PermanentProcessingError(str(exc)) from exc
    # TransientSendError (подкласс TransientProcessingError) пробрасывается
    # как есть — consumer.py её ретраит с тем же attempt_id (см.
    # src/consumer.py), поэтому следующий заход в _claim_for_sending узнает
    # свою же 'sending'-запись и продолжит без повторной пометки.

    await _record_result(pool, message, status="sent")
    logger.info(f"notification_id={message.notification_id} sent")
