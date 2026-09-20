"""Идемпотентность send-стадии в чистом виде: публикуем одно и то же
сообщение (тот же notification_id) в notifications.ready.v1 дважды, в обход
render-стадии — воркер не должен продублировать письмо. Это ключевой тест
на требование "ретраи не должны дублировать письма пользователю": render-
стадия и так не переиздаёт одно и то же сообщение при redelivery (проверка
статуса перед рендером, см. test_email_delivery_smoke для сквозного пути),
но этот тест целенаправленно проверяет именно защиту send-стадии
(notifications.status='sending'/lease), а не полагается на неё случайно."""

import asyncio
import uuid
from datetime import datetime, timezone

from .conftest import wait_until


async def test_duplicate_ready_message_sends_email_once(
    register_user, mailhog, db_conn, kafka_ready_producer
):
    user = await register_user(full_name="Дедуп Тестов")
    notification_id = uuid.uuid4()
    content_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await db_conn.execute(
        """
        INSERT INTO notification_contents (content_id, template_id, rendered_subject, rendered_body, created_at)
        VALUES ($1, NULL, $2, $3, now())
        """,
        content_id,
        "Дублирующееся письмо",
        "Это письмо должно быть отправлено ровно один раз.",
    )
    await db_conn.execute(
        """
        INSERT INTO notifications
            (notification_id, content_id, campaign_id, user_id, channel, status, scheduled_at, last_update, created_at)
        VALUES ($1, $2, NULL, $3, 'email', 'pending', $4, now(), now())
        """,
        notification_id,
        content_id,
        user["id"],
        now,
    )

    ready_message = {
        "notification_id": str(notification_id),
        "request_id": str(uuid.uuid4()),
        "schema_version": 1,
        "source_service": "notification-worker-e2e-test",
        "campaign_id": None,
        "user_id": user["id"],
        "channel": "email",
        "recipient_email": user["email"],
        "subject": "Дублирующееся письмо",
        "body": "Это письмо должно быть отправлено ровно один раз.",
        "context": {},
        "occurred_at": now.isoformat(),
        "received_at": now.isoformat(),
        "rendered_at": now.isoformat(),
    }

    # Одна и та же партиция (ключ = user_id) — доставка по порядку,
    # второе сообщение неизбежно обрабатывается после того, как первое уже
    # получило терминальный статус.
    await kafka_ready_producer(str(user["id"]), ready_message)
    await kafka_ready_producer(str(user["id"]), ready_message)

    # subject= обязателен: register_user() параллельно триггерит настоящее
    # приветственное письмо auth_service на тот же адрес (см.
    # auth_service/src/api/v1/auth.py) — без фильтра оно попало бы в счёт
    # "сколько писем доставлено" наравне с тестовым.
    subject = ready_message["subject"]
    message = await mailhog.wait_for_message(user["email"], subject=subject, timeout=30.0)
    assert message is not None, "email did not arrive in MailHog within timeout"

    # Даём воркеру время на случай, если бы он (ошибочно) отправил второе
    # письмо — короткая пауза после первого успешного результата.
    await asyncio.sleep(5.0)

    delivered = await mailhog.find_by_recipient(user["email"], subject=subject)
    assert len(delivered) == 1, f"expected exactly one email, got {len(delivered)}"

    async def _final_status():
        row = await db_conn.fetchrow(
            "SELECT status FROM notifications WHERE notification_id = $1",
            notification_id,
        )
        return row if row and row["status"] == "sent" else None

    assert await wait_until(_final_status, timeout=10.0) is not None

    history_rows = await db_conn.fetch(
        "SELECT status FROM notification_history WHERE notification_id = $1 ORDER BY sent_at",
        notification_id,
    )
    statuses = [r["status"] for r in history_rows]
    assert statuses == ["sending", "sent"], statuses
