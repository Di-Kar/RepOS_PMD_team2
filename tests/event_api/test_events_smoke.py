"""HTTP -> Kafka смоук-тесты /api/v1/events: события по контракту
docs/user_events_contract.md доходят до брокера в нужный топик."""
import uuid

from .conftest import (
    TOPIC_CLICKS,
    TOPIC_CUSTOM_EVENTS,
    TOPIC_PAGEVIEWS,
    make_event,
    post_batch,
    post_event,
)


class TestClick:
    async def test_click_reaches_kafka(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_CLICKS)
        event = make_event(
            "click",
            {"element_id": "play-button", "element_type": "button", "zone": "hero", "attrs": {"content_id": "tt1"}},
        )

        status, body = await post_event(session, event)
        assert status == 202, body
        assert body["status"] == "accepted"
        assert body["event_id"] == event["event_id"]

        message = await watcher.wait_for(lambda record, value: value["event_id"] == event["event_id"])
        assert message is not None, "событие не дошло до Kafka за отведённое время"
        assert message["event_type"] == "click"
        assert message["session_id"] == event["session_id"]
        assert message["payload"]["element_id"] == "play-button"
        assert "received_at" in message


class TestPageView:
    async def test_start_end_pair_reaches_kafka(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_PAGEVIEWS)
        session_id = str(uuid.uuid4())
        page_view_id = f"pv-{uuid.uuid4().hex[:8]}"

        start = make_event(
            "page_view_start",
            {"page_view_id": page_view_id, "page_type": "movie_card", "page_id": "tt0111161"},
            session_id=session_id,
            sequence_number=1,
        )
        end = make_event(
            "page_view_end",
            {
                "page_view_id": page_view_id,
                "page_type": "movie_card",
                "page_id": "tt0111161",
                "duration_ms": 42000,
                "tab_active": True,
            },
            session_id=session_id,
            sequence_number=2,
        )

        for event in (start, end):
            status, body = await post_event(session, event)
            assert status == 202, body
            assert body["status"] == "accepted"

        seen = {}

        def collect(record, value):
            if value["payload"].get("page_view_id") == page_view_id:
                seen[value["event_type"]] = value
            return len(seen) == 2

        await watcher.wait_for(collect)
        assert "page_view_start" in seen and "page_view_end" in seen
        assert seen["page_view_end"]["payload"]["duration_ms"] == 42000


class TestCustomEvent:
    async def test_quality_change_reaches_kafka(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_CUSTOM_EVENTS)
        event = make_event(
            "custom_event",
            {
                "custom_event_type": "quality_change",
                "content_id": "tt0111161",
                "watch_session_id": f"ws-{uuid.uuid4().hex[:8]}",
                "from_quality": "720p",
                "to_quality": "1080p",
            },
        )
        status, body = await post_event(session, event)
        assert status == 202, body
        assert body["status"] == "accepted"

        message = await watcher.wait_for(lambda record, value: value["event_id"] == event["event_id"])
        assert message is not None
        assert message["payload"]["custom_event_type"] == "quality_change"

    async def test_watch_complete_and_search_filter(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_CUSTOM_EVENTS)
        watch_complete = make_event(
            "custom_event", {"custom_event_type": "watch_complete", "content_id": "tt1", "progress_percent": 96.5}
        )
        search_filter = make_event(
            "custom_event",
            {
                "custom_event_type": "search_filter",
                "filter_type": "genre",
                "filter_value": "drama",
                "result_count": 12,
            },
        )

        for event in (watch_complete, search_filter):
            status, body = await post_event(session, event)
            assert status == 202, body
            assert body["status"] == "accepted"

        ids = {watch_complete["event_id"], search_filter["event_id"]}
        found: set = set()

        def collect(record, value):
            if value["event_id"] in ids:
                found.add(value["event_id"])
            return found == ids

        await watcher.wait_for(collect)
        assert found == ids


class TestBatch:
    async def test_batch_publishes_all(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_CLICKS)
        events = [
            make_event("click", {"element_id": f"card-{i}", "element_type": "card", "zone": "catalog", "attrs": {}})
            for i in range(3)
        ]

        status, body = await post_batch(session, events)
        assert status == 202, body
        assert len(body["results"]) == 3
        assert all(result["status"] == "accepted" for result in body["results"])

        ids = {event["event_id"] for event in events}
        found: set = set()

        def collect(record, value):
            if value["event_id"] in ids:
                found.add(value["event_id"])
            return found == ids

        await watcher.wait_for(collect)
        assert found == ids

    async def test_batch_partial_validation_failure(self, session):
        good = make_event("click", {"element_id": "x", "element_type": "button", "zone": "hero", "attrs": {}})
        bad = make_event("click", {"element_id": "x", "element_type": "button", "zone": "hero", "attrs": {}})
        del bad["user_id"]  # ни user_id, ни anonymous_id -> должно быть отклонено

        status, body = await post_batch(session, [good, bad])
        assert status == 202, body
        results_by_id = {result["event_id"]: result for result in body["results"]}
        assert results_by_id[good["event_id"]]["status"] == "accepted"
        assert results_by_id[bad["event_id"]]["status"] == "rejected"
        assert results_by_id[bad["event_id"]]["errors"]


class TestValidationAndConsent:
    async def test_missing_identity_rejected(self, session):
        event = make_event("click", {"element_id": "x", "element_type": "button", "zone": "hero", "attrs": {}})
        del event["user_id"]

        status, body = await post_event(session, event)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["errors"]

    async def test_unknown_event_type_rejected(self, session):
        event = make_event("click", {"element_id": "x", "element_type": "button", "zone": "hero", "attrs": {}})
        event["event_type"] = "heartbeat"

        status, body = await post_event(session, event)
        assert status == 202, body
        assert body["status"] == "rejected"

    async def test_no_consent_not_forwarded(self, session, kafka_watcher):
        watcher = await kafka_watcher(TOPIC_CLICKS)
        event = make_event(
            "click",
            {"element_id": "no-consent", "element_type": "button", "zone": "hero", "attrs": {}},
            consent=False,
        )

        status, body = await post_event(session, event)
        assert status == 202, body
        assert body["status"] == "skipped_no_consent"

        message = await watcher.wait_for(lambda record, value: value["event_id"] == event["event_id"], timeout=5)
        assert message is None, "событие без consent не должно публиковаться в Kafka"
