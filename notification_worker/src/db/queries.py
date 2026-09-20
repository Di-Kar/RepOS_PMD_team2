"""Прямой SQL к notifications_db — таблицы из двух чужих схем плюс одна
собственная таблица воркера:

- `notification_log` (SQLAlchemy/Alembic, notification_api) — воркер только
  обновляет `status` по `notification_id` (контракт §9).
- `message_templates` / `notification_contents` / `notifications` /
  `notification_history` (Django, notification_admin_panel) — существовали в
  БД без единого писателя (только read-only REST в admin_panel) до этого
  воркера; он заполняет их по прямому назначению (рендер → content +
  notification; отправка → history + статус).
- `notification_worker_dlq` (собственная таблица воркера, см.
  scripts/migrations/001_create_worker_dlq.sql) — сообщения, которые не
  удалось обработать (постоянная ошибка) или которые требуют ручного
  разбора (неоднозначное состояние `sending`).

Все функции принимают `db` — либо asyncpg.Pool (для одиночного запроса),
либо asyncpg.Connection, полученный из пула внутри транзакции
(`async with pool.acquire() as conn: async with conn.transaction(): ...`) —
обе стороны совместимы по интерфейсу execute/fetchrow/fetchval.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional, Union

import asyncpg

logger = logging.getLogger(__name__)

DBLike = Union[asyncpg.Pool, asyncpg.Connection]


# --- notification_log (notification_api, §9) ---------------------------------


async def update_notification_log_status(
    db: DBLike, notification_id: uuid.UUID, status: str
) -> None:
    await db.execute(
        "UPDATE notification_log SET status = $1 WHERE notification_id = $2",
        status,
        notification_id,
    )


# --- message_templates (notification_admin_panel, read-only для воркера) -----


async def get_active_template(
    db: DBLike, template_id: str
) -> Optional[dict[str, str]]:
    """Возвращает {"subject": ..., "body": ...} для активного шаблона, либо
    None (не найден/не активен/template_id не парсится как id таблицы —
    все три случая воркер трактует как постоянную ошибку 'шаблон не
    найден', не ретраит)."""
    try:
        template_pk = int(template_id)
    except (TypeError, ValueError):
        return None
    row = await db.fetchrow(
        "SELECT subject, body FROM message_templates WHERE id = $1 AND is_active = true",
        template_pk,
    )
    if row is None:
        return None
    return {"subject": row["subject"], "body": row["body"]}


# --- notifications / notification_contents (notification_admin_panel) --------


async def get_notification_status(
    db: DBLike, notification_id: uuid.UUID, *, for_update: bool = False
) -> Optional[str]:
    """Текущий статус notifications.notification_id — основа идемпотентности
    (§5.1/§5.2 плана): и рендер-, и send-стадия перед работой проверяют, не
    обработано ли уже это сообщение (redelivery)."""
    query = "SELECT status FROM notifications WHERE notification_id = $1"
    if for_update:
        query += " FOR UPDATE"
    return await db.fetchval(query, notification_id)


def _coerce_campaign_id(campaign_id: str | None) -> Optional[int]:
    """campaign_id в Kafka-сообщении — строка (контракт §4), а FK в
    notifications.campaign_id — bigint на campaigns(id). Не парсится/пусто —
    NULL, это осознанно (заявки без кампании, например моментальные
    уведомления auth_service, всегда идут без campaign_id)."""
    if not campaign_id:
        return None
    try:
        return int(campaign_id)
    except ValueError:
        return None


def _is_campaign_fk_violation(exc: asyncpg.ForeignKeyViolationError) -> bool:
    """Отличает нарушение FK notifications.campaign_id -> campaigns(id) от
    любого другого нарушения целостности той же вставки. PostgreSQL не
    сообщает в FK-ошибке имя колонки, поэтому смотрим на имя ограничения
    (автоимя и в Django-схеме, и в ddl.sql содержит `campaign_id`) и, как
    запасной вариант, на detail ('Key (campaign_id)=(42) is not present in
    table "campaigns"'). Второй FK этой таблицы — content_id — так не
    совпадёт, и его нарушение не будет замаскировано записью с NULL."""
    return "campaign_id" in ((exc.constraint_name or "") + (exc.detail or ""))


_CAMPAIGN_FK_NAME_SQL = """
    SELECT quote_ident(conname)
    FROM pg_constraint
    WHERE conrelid = to_regclass('notifications')
      AND confrelid = to_regclass('campaigns')
      AND contype = 'f'
      AND condeferred
"""

# Кэш результата _deferred_campaign_fk_name на процесс: имя ограничения не
# меняется без миграции, а сам воркер долгоживущий. _FK_NAME_UNRESOLVED
# отличает "ещё не спрашивали" от "спросили, отложенного FK нет".
_FK_NAME_UNRESOLVED = object()
_campaign_fk_name: Any = _FK_NAME_UNRESOLVED


async def _deferred_campaign_fk_name(db: DBLike) -> Optional[str]:
    """Имя (уже в кавычках, quote_ident) FK notifications.campaign_id ->
    campaigns, если оно DEFERRABLE INITIALLY DEFERRED — так его создаёт
    Django-миграция notification_admin_panel, и тогда проверка по умолчанию
    откладывается до COMMIT. None — ограничение проверяется сразу
    (например, схема из ddl.sql), форсировать нечего."""
    global _campaign_fk_name
    if _campaign_fk_name is _FK_NAME_UNRESOLVED:
        _campaign_fk_name = await db.fetchval(_CAMPAIGN_FK_NAME_SQL)
    return _campaign_fk_name


async def insert_content_and_notification(
    db: asyncpg.Connection,
    *,
    notification_id: uuid.UUID,
    template_pk: Optional[int],
    campaign_id: str | None,
    user_id: uuid.UUID,
    channel: str,
    rendered_subject: str,
    rendered_body: str,
    status: str,
    scheduled_at: datetime,
) -> None:
    """Пишет notification_contents + notifications в одной транзакции
    (вызывающий должен передать conn внутри `async with conn.transaction()`).
    notification_id передаётся явно из Kafka-сообщения (НЕ Django-дефолтный
    uuid4) — иначе кросс-сервисная корреляция по ID сломается (контракт §6).
    ON CONFLICT DO NOTHING на notifications — идемпотентность при
    redelivery поверх уже проверенного статуса (§5.1 п.2). Вставка
    notifications идёт во вложенной транзакции (SAVEPOINT) с принудительной
    немедленной проверкой FK, чтобы нарушение ссылки на кампанию всплыло
    здесь, а запасной вариант с campaign_id=NULL выполнялся в живой, а не
    прерванной транзакции — см. _is_campaign_fk_violation."""
    content_id = uuid.uuid4()
    await db.execute(
        """
        INSERT INTO notification_contents (content_id, template_id, rendered_subject, rendered_body, created_at)
        VALUES ($1, $2, $3, $4, now())
        """,
        content_id,
        template_pk,
        rendered_subject,
        rendered_body,
    )
    coerced_campaign_id = _coerce_campaign_id(campaign_id)
    campaign_fk_name = await _deferred_campaign_fk_name(db)
    try:
        # Вложенная транзакция — asyncpg выпускает SAVEPOINT внутри уже
        # открытой вызывающим транзакции. Без него неудачный INSERT
        # переводит всю транзакцию в aborted, и запасная вставка ниже
        # падала бы с InFailedSQLTransactionError, хотя исключение
        # перехвачено (найдено ревью).
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO notifications
                    (notification_id, content_id, campaign_id, user_id, channel, status,
                     scheduled_at, last_update, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now())
                ON CONFLICT (notification_id) DO NOTHING
                """,
                notification_id,
                content_id,
                coerced_campaign_id,
                user_id,
                channel,
                status,
                scheduled_at,
            )
            if campaign_fk_name is not None:
                # Django создаёт этот FK как DEFERRABLE INITIALLY DEFERRED,
                # поэтому по умолчанию campaign_id проверяется только на
                # COMMIT внешней транзакции — там перехватить и исправить
                # ошибку уже нельзя (она улетала в consumer, и уведомление
                # уходило в DLQ). Форсируем проверку здесь, внутри savepoint,
                # и сразу возвращаем режим: IMMEDIATE действует до конца
                # транзакции, то есть протёк бы в остальные запросы
                # вызывающего.
                await db.execute(f"SET CONSTRAINTS {campaign_fk_name} IMMEDIATE")
                await db.execute(f"SET CONSTRAINTS {campaign_fk_name} DEFERRED")
    except asyncpg.ForeignKeyViolationError as exc:
        if not _is_campaign_fk_violation(exc):
            raise
        # campaign_id ссылается на несуществующую (например, удалённую)
        # кампанию — не блокируем доставку уведомления пользователю из-за
        # разъехавшихся справочных данных, просто теряем связь с кампанией.
        # Откат дошёл только до savepoint, поэтому записанный выше
        # notification_contents остаётся, а транзакция снова пригодна для
        # запросов.
        logger.warning(
            f"notification_id={notification_id}: campaign_id={coerced_campaign_id} "
            f"not found in campaigns, inserting notification with campaign_id=NULL"
        )
        await db.execute(
            """
            INSERT INTO notifications
                (notification_id, content_id, campaign_id, user_id, channel, status,
                 scheduled_at, last_update, created_at)
            VALUES ($1, $2, NULL, $3, $4, $5, $6, now(), now())
            ON CONFLICT (notification_id) DO NOTHING
            """,
            notification_id,
            content_id,
            user_id,
            channel,
            status,
            scheduled_at,
        )


async def get_status_for_claim(
    db: asyncpg.Connection, notification_id: uuid.UUID
) -> Optional[str]:
    """Читает status с блокировкой строки (FOR UPDATE) — вызывающий должен
    быть внутри транзакции. Основа claim-логики send-стадии (§5.2 плана)."""
    return await db.fetchval(
        "SELECT status FROM notifications WHERE notification_id = $1 FOR UPDATE",
        notification_id,
    )


async def get_latest_sending_attempt(
    db: DBLike, notification_id: uuid.UUID
) -> Optional[str]:
    """Возвращает attempt_id (записанный в error_message строки истории
    статуса 'sending', см. send_service.mark_sending) последней попытки
    отправки — используется, чтобы отличить "это я сам продолжаю ту же,
    ещё не прервавшуюся серию ретраев" от "эту запись 'sending' оставил
    другой (упавший) вызов", без угадывания по времени (см. ревью:
    time-based лиз не мог надёжно различить эти два случая)."""
    return await db.fetchval(
        "SELECT error_message FROM notification_history "
        "WHERE notification_id = $1 AND status = 'sending' "
        "ORDER BY sent_at DESC LIMIT 1",
        notification_id,
    )


async def mark_sending(
    db: DBLike, notification_id: uuid.UUID, attempt_id: uuid.UUID
) -> None:
    """pending -> sending, проставляет last_notification_send=now() (чисто
    информационно, для дашборда) и записывает attempt_id этой попытки в
    notification_history — по нему следующий вызов claim-логики отличит
    "свой" продолжающийся ретрай от чужого прерванного (см.
    get_latest_sending_attempt)."""
    await db.execute(
        "UPDATE notifications SET status = 'sending', last_notification_send = now(), "
        "last_update = now() WHERE notification_id = $1",
        notification_id,
    )
    await insert_notification_history(
        db, notification_id, "sending", error_message=str(attempt_id)
    )


async def get_latest_send_confirmation(
    db: DBLike, notification_id: uuid.UUID
) -> Optional[str]:
    """Возвращает attempt_id (записанный в error_message строки истории
    статуса 'sent_by_smtp') последнего подтверждённого SMTP приёма письма —
    в отличие от get_latest_sending_attempt, это не "кто последний застолбил
    claim", а "SMTP уже точно принял письмо в этой попытке". Совпадение
    attempt_id у статуса 'sending' само по себе не доказывает, что письмо
    ещё не отправлено (см. ревью) — эта проверка закрывает разрыв: claim-
    логика (send_service._claim_for_sending) запрещает повторный send_email
    при ЛЮБОМ таком подтверждении, чьим бы attempt_id оно ни было
    подписано, и разрешает только повторную запись результата. Сам
    attempt_id в записи остаётся для разбора руками."""
    return await db.fetchval(
        "SELECT error_message FROM notification_history "
        "WHERE notification_id = $1 AND status = 'sent_by_smtp' "
        "ORDER BY sent_at DESC LIMIT 1",
        notification_id,
    )


async def mark_sent_by_smtp(
    db: DBLike, notification_id: uuid.UUID, attempt_id: uuid.UUID
) -> None:
    """Дешёвая, отдельная от _record_result запись сразу после того, как
    SMTP подтвердил приём письма — до попытки финализировать статус в
    notifications/notification_log. Если финализация потом упадёт по вине
    БД, эта запись позволит следующему заходу (get_latest_send_confirmation)
    отличить "письмо уже точно ушло, слать повторно нельзя" от "ещё не
    отправляли" (см. send_service._claim_for_sending / _finalize_sent)."""
    await insert_notification_history(
        db,
        notification_id,
        "sent_by_smtp",
        error_message=str(attempt_id),
        delivery_provider="smtp",
    )


async def get_existing_rendered_content(
    db: DBLike, notification_id: uuid.UUID
) -> Optional[dict[str, str]]:
    """Контент, уже отрендеренный и сохранённый в предыдущей попытке
    рендер-стадии — используется, когда notifications.status уже 'pending'
    при повторном чтении того же Kafka-сообщения (см.
    render_service._resume_pending): не рендерим повторно, публикуем то,
    что уже есть, в notifications.ready.v1."""
    row = await db.fetchrow(
        "SELECT nc.rendered_subject, nc.rendered_body FROM notifications n "
        "JOIN notification_contents nc ON nc.content_id = n.content_id "
        "WHERE n.notification_id = $1",
        notification_id,
    )
    if row is None:
        return None
    return {"subject": row["rendered_subject"], "body": row["rendered_body"]}


async def update_notification_status(
    db: DBLike,
    notification_id: uuid.UUID,
    status: str,
    *,
    sent_at: Optional[datetime] = None,
) -> None:
    if sent_at is not None:
        await db.execute(
            "UPDATE notifications SET status = $1, sent_at = $2, last_update = now() "
            "WHERE notification_id = $3",
            status,
            sent_at,
            notification_id,
        )
    else:
        await db.execute(
            "UPDATE notifications SET status = $1, last_update = now() "
            "WHERE notification_id = $2",
            status,
            notification_id,
        )


async def insert_notification_history(
    db: DBLike,
    notification_id: uuid.UUID,
    status: str,
    *,
    error_message: str = "",
    delivery_provider: str = "",
) -> None:
    await db.execute(
        """
        INSERT INTO notification_history
            (notification_id, status, sent_at, error_message, delivery_provider)
        VALUES ($1, $2, now(), $3, $4)
        """,
        notification_id,
        status,
        error_message,
        delivery_provider,
    )


# --- notification_worker_dlq (собственная таблица воркера) -------------------


async def insert_dlq(
    db: DBLike,
    *,
    notification_id: Optional[uuid.UUID],
    stage: str,
    error_type: str,
    error_message: str = "",
    raw_message: Optional[dict[str, Any]] = None,
    attempt_count: int = 1,
) -> None:
    await db.execute(
        """
        INSERT INTO notification_worker_dlq
            (notification_id, stage, error_type, error_message, raw_message, attempt_count)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        """,
        notification_id,
        stage,
        error_type,
        error_message,
        json.dumps(raw_message, default=str) if raw_message is not None else None,
        attempt_count,
    )
