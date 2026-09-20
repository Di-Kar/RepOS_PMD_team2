"""Пользователь с is_active=false в auth_service: воркер не должен
отправлять письмо и не должен ретраить его бесконечно — терминальный
статус 'skipped', видимый и в notifications, и в notification_log.

Проверки идут через notification_id, полученный из notification_log по
request_id этой конкретной заявки — не через "последнее уведомление этого
user_id": register_user() успевает запустить настоящее приветственное
письмо auth_service ДО деактивации (background task), и если деактивация
происходит быстрее, чем этот фоновый пайплайн доходит до рендер-стадии,
приветственное уведомление тоже получает статус 'skipped' для того же
user_id — выборка "по user_id" могла бы случайно зацепить его, а не
уведомление этого теста."""

from .conftest import make_notification_request, post_notification, wait_until


async def test_inactive_user_is_skipped_without_sending(
    session, register_user, auth_db_conn, mailhog, db_conn
):
    user = await register_user(full_name="Неактивный Пользователь")
    await auth_db_conn.execute(
        "UPDATE users SET is_active = false WHERE id = $1", user["id"]
    )

    request = make_notification_request(recipient_ids=[user["id"]])
    status, body = await post_notification(session, request)
    assert status == 202, body

    async def _resolve_notification_id():
        return await db_conn.fetchval(
            "SELECT notification_id FROM notification_log WHERE request_id = $1",
            request["request_id"],
        )

    notification_id = await wait_until(_resolve_notification_id, timeout=15.0)
    assert notification_id is not None, "notification_log row was never created"

    async def _check_skipped():
        status = await db_conn.fetchval(
            "SELECT status FROM notifications WHERE notification_id = $1",
            notification_id,
        )
        return status if status == "skipped" else None

    assert await wait_until(_check_skipped, timeout=15.0) is not None, (
        "notifications.status never reached 'skipped'"
    )

    log_status = await db_conn.fetchval(
        "SELECT status FROM notification_log WHERE request_id = $1",
        request["request_id"],
    )
    assert log_status == "skipped"

    # subject= обязателен: register_user() успевает отправить настоящее
    # приветственное письмо ДО деактивации (auth_service, background task) —
    # без фильтра по теме тест искал бы вообще любое письмо этому адресу.
    found = await mailhog.find_by_recipient(
        user["email"], subject=request["subject_override"]
    )
    assert found == [], "email must not be sent to an inactive user"
