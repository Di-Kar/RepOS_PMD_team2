"""Базовый happy-path: реальный пользователь -> заявка без шаблона
(text_override) -> письмо доходит до MailHog -> статусы обновлены во всех
трёх местах, за которые отвечает notification_worker (notification_log,
notifications, notification_history).

Все проверки идут через конкретный notification_id, полученный из
notification_log по request_id этой заявки — не через user_id: register_user()
попутно триггерит настоящее приветственное письмо auth_service на тот же
адрес (см. auth_service/src/api/v1/auth.py, send_welcome_notification), у
которого свой отдельный notification_id, и выборка "по user_id" находила бы
обе строки сразу."""

from .conftest import make_notification_request, post_notification, wait_until


async def test_email_delivered_and_statuses_updated(session, register_user, mailhog, db_conn):
    user = await register_user(full_name="Смоук Тестов")
    request = make_notification_request(
        recipient_ids=[user["id"]],
        subject_override="Смоук-тест воркера",
        text_override="Здравствуйте! Это тестовое письмо.",
    )

    status, body = await post_notification(session, request)
    assert status == 202, body
    assert body["status"] == "accepted", body

    message = await mailhog.wait_for_message(
        user["email"], subject="Смоук-тест воркера", timeout=30.0
    )
    assert message is not None, "email did not arrive in MailHog within timeout"
    assert "тестовое письмо" in mailhog.body(message)

    async def _resolve_notification_id():
        return await db_conn.fetchval(
            "SELECT notification_id FROM notification_log WHERE request_id = $1",
            request["request_id"],
        )

    notification_id = await wait_until(_resolve_notification_id, timeout=15.0)
    assert notification_id is not None, "notification_log row was never created"

    async def _check_sent():
        row = await db_conn.fetchrow(
            "SELECT status, sent_at FROM notifications WHERE notification_id = $1",
            notification_id,
        )
        return row if row and row["status"] == "sent" else None

    notification_row = await wait_until(_check_sent, timeout=15.0)
    assert notification_row is not None, "notifications.status never reached 'sent'"
    assert notification_row["sent_at"] is not None

    log_status = await db_conn.fetchval(
        "SELECT status FROM notification_log WHERE request_id = $1",
        request["request_id"],
    )
    assert log_status == "sent"

    history_statuses = await db_conn.fetch(
        "SELECT status FROM notification_history WHERE notification_id = $1 ORDER BY sent_at",
        notification_id,
    )
    assert [r["status"] for r in history_statuses] == ["sending", "sent"]
