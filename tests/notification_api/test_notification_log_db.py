"""Лог заявок в БД notification_api (notification_log,
docs/notification_requests_contract.md §9): после публикации в Kafka
появляется строка с соответствующим статусом; повторная отправка той же
заявки (тот же request_id) обновляет строку, а не падает на конфликте PK."""

import uuid

from .conftest import TOPIC_REQUESTS, make_request, post_notification


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
        assert row["status"] == "kafka_published"

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
        assert rows[0]["status"] == "kafka_published"
