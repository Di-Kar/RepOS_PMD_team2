"""Валидация и публикация одного события в Kafka."""
import logging

from pydantic import TypeAdapter, ValidationError

from src.core.kafka_producer import publish_event
from src.models.responses import EventResult
from src.models.schemas import TOPIC_BY_EVENT_TYPE, UserEvent, to_kafka_record

logger = logging.getLogger(__name__)

_event_adapter: TypeAdapter = TypeAdapter(UserEvent)


async def process_event(raw: dict) -> EventResult:
    """Валидирует событие (FR-27) и публикует в Kafka. Некорректные события
    не роняют весь batch — помечаются status="rejected" (NFR-18), клиент по
    FR-29 может переотправить их после исправления."""
    try:
        event = _event_adapter.validate_python(raw)
    except ValidationError as exc:
        event_id = raw.get("event_id") if isinstance(raw, dict) else None
        errors = [f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()]
        return EventResult(event_id=str(event_id) if event_id else None, status="rejected", errors=errors)

    if not event.consent:
        logger.info(f"Event {event.event_id} skipped: consent=false")
        return EventResult(event_id=str(event.event_id), status="skipped_no_consent")

    topic_key = TOPIC_BY_EVENT_TYPE[event.event_type]
    record = to_kafka_record(event)
    try:
        await publish_event(topic_key, key=str(event.session_id), value=record)
    except Exception as exc:
        logger.error(f"Failed to publish event {event.event_id} to Kafka: {exc}")
        return EventResult(event_id=str(event.event_id), status="rejected", errors=["kafka_publish_failed"])

    return EventResult(event_id=str(event.event_id), status="accepted")
