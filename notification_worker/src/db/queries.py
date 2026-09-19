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
import uuid
from datetime import datetime
from typing import Any, Optional, Union

import asyncpg

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
    redelivery поверх уже проверенного статуса (§5.1 п.2)."""
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
    try:
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
    except asyncpg.ForeignKeyViolationError:
        # campaign_id ссылается на несуществующую (например, удалённую)
        # кампанию — не блокируем доставку уведомления пользователю из-за
        # разъехавшихся справочных данных, просто теряем связь с кампанией.
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


async def get_notification_for_claim(
    db: asyncpg.Connection, notification_id: uuid.UUID
) -> Optional[asyncpg.Record]:
    """Читает status + last_notification_send с блокировкой строки
    (FOR UPDATE) — вызывающий должен быть внутри транзакции. Основа
    claim-логики send-стадии (§5.2 плана): last_notification_send здесь
    используется как лиз (см. settings.send_lease_seconds), а не только как
    информационная метка."""
    return await db.fetchrow(
        "SELECT status, last_notification_send FROM notifications "
        "WHERE notification_id = $1 FOR UPDATE",
        notification_id,
    )


async def mark_sending(db: DBLike, notification_id: uuid.UUID) -> None:
    """pending -> sending, проставляет лиз (last_notification_send=now())."""
    await db.execute(
        "UPDATE notifications SET status = 'sending', last_notification_send = now(), "
        "last_update = now() WHERE notification_id = $1",
        notification_id,
    )


async def touch_sending_lease(db: DBLike, notification_id: uuid.UUID) -> None:
    """Продлевает лиз без смены статуса — вызывается при ретрае SMTP
    в рамках того же процесса/сообщения (ещё не поводов считать
    'sending' зависшим)."""
    await db.execute(
        "UPDATE notifications SET last_notification_send = now() WHERE notification_id = $1",
        notification_id,
    )


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
