"""Лог заявок в БД notification_api (notification_log,
docs/notification_requests_contract.md §9): после публикации в Kafka
появляется строка с соответствующим статусом; повторная отправка той же
заявки (тот же request_id) обновляет строку, а не падает на конфликте PK.

Тесты используют случайный (несуществующий) recipient_id — в этом окружении
рядом реально работает notification_worker (S10_T3), который подхватывает
это же сообщение из notifications.requests.v1, не находит пользователя в
auth_service и почти сразу переводит статус в 'render_failed' (корректное
поведение по контракту §9 — "воркер обновляет ту же строку"). Из-за этого
статус сразу после публикации — не строго 'kafka_published' навсегда, а
'kafka_published' либо (если воркер уже успел) 'render_failed': оба значения
для теста означают "notification_api строку создал и не задвоил", что и
является предметом проверки."""

import uuid

from .conftest import TOPIC_REQUESTS, make_request, post_notification

# Статусы, ожидаемые сразу после публикации в этом окружении: собственный
# статус notification_api либо терминальный статус, который параллельно
# работающий notification_worker успевает проставить для заведомо
# несуществующего recipient_id (см. модуль-докстринг).
_ACCEPTABLE_STATUSES = {"kafka_published", "render_failed"}


class TestNotificationLog:
    async def test_log_row_created_after_publish(self, session, kafka_watcher, db_conn):
        watcher = await kafka_watcher(TOPIC_REQUESTS)
        recipient_id = str(uuid.uuid4())
        request = make_request(recipient_ids=[recipient_id])

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "accepted"

        message = await watcher.wait_for(
            lambda record, value: value["request_id"] == request["request_id"]
            and value["user_id"] == recipient_id
        )
        assert message is not None, "заявка не дошла до Kafka за отведённое время"

        row = await db_conn.fetchrow(
            "SELECT request_id, user_id, channel, status "
            "FROM notification_log WHERE notification_id = $1",
            uuid.UUID(message["notification_id"]),
        )
        assert row is not None, "строка лога не появилась в notification_log"
        assert str(row["request_id"]) == request["request_id"]
        assert str(row["user_id"]) == recipient_id
        assert row["channel"] == "email"
        assert row["status"] in _ACCEPTABLE_STATUSES, row["status"]

    async def test_retry_same_request_id_upserts_log_row(
        self, session, kafka_watcher, db_conn
    ):
        """Повторная отправка заявки с тем же request_id даёт тот же
        notification_id (§6) — вторая попытка должна обновить существующую
        строку, а не упасть на конфликте первичного ключа."""
        watcher = await kafka_watcher(TOPIC_REQUESTS)
        recipient_id = str(uuid.uuid4())
        request = make_request(recipient_ids=[recipient_id])

        for _ in range(2):
            status, body = await post_notification(session, request)
            assert status == 202, body
            assert body["status"] == "accepted"

        message = await watcher.wait_for(
            lambda record, value: value["request_id"] == request["request_id"]
            and value["user_id"] == recipient_id
        )
        assert message is not None

        rows = await db_conn.fetch(
            "SELECT status FROM notification_log WHERE notification_id = $1",
            uuid.UUID(message["notification_id"]),
        )
        assert len(rows) == 1, "ретрай должен обновить строку, а не создать вторую"
        assert rows[0]["status"] in _ACCEPTABLE_STATUSES, rows[0]["status"]
