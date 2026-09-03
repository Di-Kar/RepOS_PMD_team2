"""Модели запросов/ответов эндпоинтов приёма событий."""

from typing import Literal

from pydantic import BaseModel, Field

EventStatus = Literal["accepted", "skipped_no_consent", "rejected"]


class EventResult(BaseModel):
    """Результат обработки одного события. event_id может быть None, если
    событие отклонено ещё до того, как удалось распарсить его event_id."""

    event_id: str | None = None
    status: EventStatus
    errors: list[str] = Field(default_factory=list)


class BatchRequest(BaseModel):
    events: list[dict] = Field(min_length=1)


class BatchResponse(BaseModel):
    results: list[EventResult]
