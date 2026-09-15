"""HTTP -> Kafka смоук-тесты /api/v1/notifications: простые невалидные заявки
отбрасываются по контракту docs/notification_requests_contract.md, а валидные
доходят до брокера в notifications.requests.v1."""

import uuid

from .conftest import TOPIC_REQUESTS, make_request, post_batch, post_notification


class TestValidation:
    """Отброс простых невалидных заявок (§5 контракта) — всегда 202, статус
    в теле, как и у event_api (NFR-3-аналог)."""

    async def test_missing_content_source_rejected(self, session):
        """Ни template_id, ни text_override — заявка отклоняется целиком."""
        request = make_request(template_id=None)

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["accepted_count"] == 0
        assert body["errors"]

    async def test_invalid_channel_rejected(self, session):
        request = make_request(channel="carrier_pigeon")

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["errors"]

    async def test_empty_recipient_ids_rejected(self, session):
        request = make_request(recipient_ids=[])

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["errors"]

    async def test_invalid_recipient_uuid_rejected_individually(self, session):
        """Один невалидный UUID среди получателей не блокирует остальных —
        попадает в rejected_recipients, а не в общий отказ заявки."""
        good_recipient = str(uuid.uuid4())
        request = make_request(recipient_ids=[good_recipient, "not-a-uuid"])

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "partially_accepted"
        assert body["accepted_count"] == 1
        reasons = {r["user_id"]: r["reason"] for r in body["rejected_recipients"]}
        assert reasons.get("not-a-uuid") == "invalid_uuid"

    async def test_all_recipients_invalid_rejected(self, session):
        request = make_request(recipient_ids=["not-a-uuid", "also-not-a-uuid"])

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["accepted_count"] == 0
        assert len(body["rejected_recipients"]) == 2


class TestKafkaDelivery:
    """Валидные заявки реально доходят до Kafka — чтобы можно было убедиться,
    что фан-аут и публикация работают, а не только HTTP-ответ."""

    async def test_notification_reaches_kafka(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_REQUESTS)
        recipient_id = str(uuid.uuid4())
        request = make_request(
            recipient_ids=[recipient_id],
            context={"movie_title": "smoke-test-movie"},
        )

        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "accepted"
        assert body["accepted_count"] == 1

        message = await watcher.wait_for(
            lambda record, value: value["request_id"] == request["request_id"]
            and value["user_id"] == recipient_id
        )
        assert message is not None, "заявка не дошла до Kafka за отведённое время"
        assert message["channel"] == "email"
        assert message["template_id"] == "1"
        assert message["context"]["movie_title"] == "smoke-test-movie"
        assert "notification_id" in message
        assert "received_at" in message

    async def test_batch_publishes_all_recipients(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_REQUESTS)
        recipient_ids = [str(uuid.uuid4()) for _ in range(3)]
        requests = [make_request(recipient_ids=[rid]) for rid in recipient_ids]

        status, body = await post_batch(session, requests)
        assert status == 202, body
        assert len(body["results"]) == 3
        assert all(result["status"] == "accepted" for result in body["results"])

        remaining = set(recipient_ids)

        def collect(record, value):
            remaining.discard(value["user_id"])
            return not remaining

        await watcher.wait_for(collect)
        assert not remaining, f"не дошли до Kafka: {remaining}"
