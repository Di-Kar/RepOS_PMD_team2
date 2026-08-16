"""Схемы событий по контракту docs/user_events_contract.md."""
from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClickPayload(Payload):
    element_id: str
    element_type: str
    zone: str
    attrs: dict = Field(default_factory=dict)


class PageViewStartPayload(Payload):
    page_view_id: str
    page_type: str
    page_id: str | None = None


class PageViewEndPayload(Payload):
    page_view_id: str
    page_type: str
    page_id: str | None = None
    duration_ms: int = Field(ge=0)
    tab_active: bool


class QualityChangePayload(Payload):
    custom_event_type: Literal["quality_change"]
    content_id: str
    watch_session_id: str
    from_quality: str
    to_quality: str


class WatchCompletePayload(Payload):
    custom_event_type: Literal["watch_complete"]
    content_id: str
    progress_percent: float = Field(ge=0, le=100)


class SearchFilterPayload(Payload):
    custom_event_type: Literal["search_filter"]
    filter_type: str
    filter_value: str
    search_session_id: str | None = None
    result_count: int | None = None


CustomEventPayload = Annotated[
    Union[QualityChangePayload, WatchCompletePayload, SearchFilterPayload],
    Field(discriminator="custom_event_type"),
]


class EventBase(BaseModel):
    """Общие поля сообщения — раздел 2 контракта."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    schema_version: int = SCHEMA_VERSION
    occurred_at: datetime
    user_id: str | None = None
    anonymous_id: str | None = None
    session_id: UUID
    sequence_number: int = Field(ge=0)
    consent: bool
    context: dict = Field(default_factory=dict)
    source: str
    # received_at выставляется сервисом при приёме (раздел 2 контракта), клиентское
    # значение, если и придёт, игнорируется — сериализуется отдельно перед публикацией.

    @model_validator(mode="after")
    def _require_identity(self) -> "EventBase":
        if not self.user_id and not self.anonymous_id:
            raise ValueError("either user_id or anonymous_id is required")
        return self


class ClickEvent(EventBase):
    event_type: Literal["click"]
    payload: ClickPayload


class PageViewStartEvent(EventBase):
    event_type: Literal["page_view_start"]
    payload: PageViewStartPayload


class PageViewEndEvent(EventBase):
    event_type: Literal["page_view_end"]
    payload: PageViewEndPayload


class CustomEvent(EventBase):
    event_type: Literal["custom_event"]
    payload: CustomEventPayload


UserEvent = Annotated[
    Union[ClickEvent, PageViewStartEvent, PageViewEndEvent, CustomEvent],
    Field(discriminator="event_type"),
]

# event_type -> топик Kafka (раздел 1 контракта)
TOPIC_BY_EVENT_TYPE: dict[str, str] = {
    "click": "clicks",
    "page_view_start": "pageviews",
    "page_view_end": "pageviews",
    "custom_event": "custom_events",
}


def to_kafka_record(event: "ClickEvent | PageViewStartEvent | PageViewEndEvent | CustomEvent") -> dict:
    """Сериализует событие в JSON-совместимый dict для value сообщения Kafka,
    проставляя received_at в момент вызова (раздел 2 контракта, NFR-17)."""
    record = event.model_dump(mode="json")
    record["received_at"] = datetime.now(timezone.utc).isoformat()
    return record
