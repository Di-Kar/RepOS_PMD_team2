"""Заявка на несуществующего пользователя — постоянная ошибка (404 от
auth_service): воркер не должен ретраить её бесконечно, а должен
зафиксировать причину в notification_worker_dlq и продолжить работать.

Тест не проверяет напрямую "разные партиции не блокируют друг друга" (это
гарантирует сам код — pause/resume только застрявшей партиции в
src/consumer.py, независимая asyncio-задача на партицию), а проверяет
наблюдаемое следствие: система не виснет и продолжает обрабатывать другие
уведомления после "ядовитого" сообщения."""

import uuid

from .conftest import make_notification_request, post_notification, wait_until


async def test_unknown_user_goes_to_dlq_and_worker_keeps_running(
    session, register_user, mailhog, db_conn
):
    unknown_user_id = str(uuid.uuid4())
    bad_request = make_notification_request(recipient_ids=[unknown_user_id])

    status, body = await post_notification(session, bad_request)
    assert status == 202, body

    async def _check_dlq():
        row = await db_conn.fetchrow(
            "SELECT error_type FROM notification_worker_dlq "
            "WHERE stage = 'render' AND error_type = 'user_not_found' "
            "AND raw_message->>'request_id' = $1",
            bad_request["request_id"],
        )
        return row

    dlq_row = await wait_until(_check_dlq, timeout=20.0)
    assert dlq_row is not None, "unknown user_id was never recorded in notification_worker_dlq"

    log_status = await db_conn.fetchval(
        "SELECT status FROM notification_log WHERE request_id = $1",
        bad_request["request_id"],
    )
    assert log_status == "render_failed"

    # Воркер продолжает нормально работать: следующее, валидное сообщение
    # доставляется в обычные сроки.
    good_user = await register_user(full_name="После Ядовитого Сообщения")
    good_request = make_notification_request(recipient_ids=[good_user["id"]])
    status, body = await post_notification(session, good_request)
    assert status == 202, body

    message = await mailhog.wait_for_message(good_user["email"], timeout=20.0)
    assert message is not None, "worker appears stuck after a poison message"
