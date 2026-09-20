"""Бизнес-логика send-стадии (email) — обрабатывает одно сообщение
notifications.ready.v1: идемпотентно отправляет письмо (проверяет текущий
статус перед отправкой — redelivery/ретрай не должен дублировать письмо),
пишет notification_history и обновляет notifications/notification_log. См.
план §5.2."""

import enum
import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg
from aiokafka.structs import ConsumerRecord
from notification_schemas import ReadyToSendMessage
from pydantic import ValidationError

from src.clients.email_client import AmbiguousSendError, PermanentSendError, send_email
from src.core.errors import PermanentProcessingError
from src.core.message_utils import safe_raw_message, try_uuid
from src.db import queries
from src.db.postgres import get_pool

logger = logging.getLogger(__name__)


class ClaimResult(enum.Enum):
    """Исход _claim_for_sending — раньше это был bool, но одного "можно
    продолжать" недостаточно: продолжение "своей" попытки в статусе
    'sending' бывает двух разных видов, требующих разных действий (см.
    ревью — совпадение attempt_id само по себе не доказывает отсутствие
    доставки)."""

    SKIP = "skip"  # ничего делать не нужно (уже обработано / не подлежит)
    SEND = "send"  # письмо ещё не уходило в этой попытке — можно send_email
    FINALIZE_ONLY = "finalize_only"  # SMTP уже подтвердил приём — только дозаписать результат, send_email не звать


async def _claim_for_sending(
    pool: asyncpg.Pool, message: ReadyToSendMessage, attempt_id: uuid.UUID
) -> ClaimResult:
    """См. ClaimResult — SKIP/SEND/FINALIZE_ONLY.

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
    сверяется точным сравнением, без угадывания по времени.

    Но само по себе совпадение attempt_id доказывает только "это тот же
    процесс/попытка", а не "письмо ещё не ушло" (см. ревью). Поэтому в
    статусе 'sending' сначала спрашивается более сильный факт — есть ли
    подтверждение приёма от SMTP (queries.mark_sent_by_smtp, пишется в
    _finalize_sent сразу после успешного send_email, ДО финализации
    статуса). Если оно есть, send_email не вызывается ни при каком
    attempt_id — только дозапись результата (FINALIZE_ONLY)."""
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
            return ClaimResult.SKIP

        if status in ("sent", "failed", "skipped"):
            logger.info(
                f"notification_id={message.notification_id} already {status}, "
                "skipping redelivery"
            )
            return ClaimResult.SKIP

        if status == "sending":
            # Проверяется ПЕРВЫМ, до сравнения attempt_id: подтверждённый
            # приём письма SMTP-сервером — факт о доставке, а не о попытке.
            # Неважно, оставила эту запись текущая серия ретраев или
            # предыдущий, упавший процесс: слать повторно нельзя ни в том,
            # ни в другом случае, осталось только дописать результат. Для
            # упавшего процесса это заодно снимает ручной разбор там, где
            # доставка на самом деле известна (ветка ниже).
            if await queries.get_latest_send_confirmation(
                conn, message.notification_id
            ):
                return ClaimResult.FINALIZE_ONLY

            current_attempt = await queries.get_latest_sending_attempt(
                conn, message.notification_id
            )
            if current_attempt == str(attempt_id):
                # Точно та же, ещё не прервавшаяся серия ретраев этого же
                # процесса на это же сообщение, письмо ещё не уходило —
                # безопасно продолжать.
                return ClaimResult.SEND
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
            return ClaimResult.SKIP

        # status == "pending"
        await queries.mark_sending(conn, message.notification_id, attempt_id)
        return ClaimResult.SEND


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


async def _flag_for_manual_review(
    pool: asyncpg.Pool,
    message: ReadyToSendMessage,
    *,
    error_type: str,
    error_message: str,
) -> None:
    """Заводит сообщение на ручной разбор (DLQ + notification_log), не давая
    сбою самой этой записи подменить исключение вызывающего: вызывающий
    поднимает PermanentProcessingError именно для того, чтобы consumer.py
    НЕ ретраил handle_message, а утёкшая отсюда ошибка БД выглядела бы для
    него транзиентной — и привела бы ровно к повторной отправке, которую мы
    предотвращаем. notifications.status намеренно не трогаем: мы не знаем,
    доставлено письмо или нет, и 'failed' был бы такой же ложью, как 'sent'
    (статус остаётся 'sending' — это и есть маркер "разобрать руками")."""
    try:
        await queries.insert_dlq(
            pool,
            notification_id=message.notification_id,
            stage="send",
            error_type=error_type,
            error_message=error_message,
            raw_message=message.model_dump(mode="json"),
        )
        await queries.update_notification_log_status(
            pool, message.notification_id, "requires_manual_review"
        )
    except Exception as exc:  # noqa: BLE001 — если БД недоступна, остаётся только лог
        logger.error(
            f"Failed to flag notification_id={message.notification_id} "
            f"for manual review ({error_type}): {exc}"
        )


async def _finalize_sent(
    pool: asyncpg.Pool,
    message: ReadyToSendMessage,
    attempt_id: uuid.UUID,
    *,
    already_confirmed: bool,
) -> None:
    """Вызывается ПОСЛЕ того, как send_email для этого уведомления уже точно
    отработал (либо только что, либо в предыдущем заходе — тогда
    already_confirmed=True) — send_email здесь не вызывается ни при каких
    обстоятельствах. Это и есть разделение "повторной отправки" и
    "повторного сохранения результата" из ревью.

    Сбой самого _record_result намеренно пробрасывается как транзиентный:
    подтверждение уже лежит в БД, поэтому повтор handle_message от
    consumer.py вернётся сюда же через ClaimResult.FINALIZE_ONLY и повторит
    ТОЛЬКО запись результата. А вот сбой записи самого подтверждения
    ретраить нельзя — следующий заход не отличил бы "письмо уже ушло" от
    "ещё не отправляли" и отправил бы второе."""
    if not already_confirmed:
        try:
            await queries.mark_sent_by_smtp(pool, message.notification_id, attempt_id)
        except Exception as exc:  # noqa: BLE001 — обязаны остановиться, какой бы ни была ошибка
            logger.error(
                f"notification_id={message.notification_id} sent by SMTP but "
                f"confirmation could not be persisted: {exc}"
            )
            await _flag_for_manual_review(
                pool,
                message,
                error_type="send_confirmation_persist_failed",
                error_message=str(exc),
            )
            raise PermanentProcessingError(
                f"email delivered but confirmation could not be persisted: {exc}"
            ) from exc

    await _record_result(pool, message, status="sent")


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

    claim = await _claim_for_sending(pool, message, attempt_id)
    if claim is ClaimResult.SKIP:
        return

    if claim is ClaimResult.SEND:
        try:
            await send_email(
                to=message.recipient_email,
                subject=message.subject,
                body=message.body,
                notification_id=message.notification_id,
            )
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
        except AmbiguousSendError as exc:
            # Обрыв уже посреди диалога с сервером — неизвестно, принял ли
            # он письмо. Автоповтор send_email здесь рискует задублировать
            # доставку (см. ревью), поэтому не отдаём это consumer.py как
            # транзиентную ошибку, а заводим на ручной разбор.
            await _flag_for_manual_review(
                pool, message, error_type="smtp_ambiguous", error_message=str(exc)
            )
            raise PermanentProcessingError(str(exc)) from exc
        # TransientSendError (подкласс TransientProcessingError) —
        # недвусмысленный отказ ДО того, как сервер начал принимать письмо
        # (явный SMTP-ответ 4xx, неудавшийся коннект) — пробрасывается как
        # есть, consumer.py её ретраит с тем же attempt_id (см.
        # src/consumer.py); следующий заход в _claim_for_sending узнает свою
        # же 'sending'-запись без подтверждения отправки и снова вернёт SEND.

    await _finalize_sent(
        pool,
        message,
        attempt_id,
        already_confirmed=claim is ClaimResult.FINALIZE_ONLY,
    )
    logger.info(f"notification_id={message.notification_id} sent")
