"""Модели запросов/ответов эндпоинтов приёма заявок на уведомления
(docs/notification_requests_contract.md §2)."""

from typing import Literal

from pydantic import BaseModel, Field

NotificationRequestStatus = Literal["accepted", "partially_accepted", "rejected"]


class RejectedRecipient(BaseModel):
    user_id: str
    reason: str


class NotificationRequestResult(BaseModel):
    """Результат обработки одной заявки (возможно, на нескольких
    получателей). request_id может быть None, если заявка отклонена ещё до
    того, как удалось распарсить её request_id."""

    request_id: str | None = None
    status: NotificationRequestStatus
    accepted_count: int = 0
    rejected_recipients: list[RejectedRecipient] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BatchRequest(BaseModel):
    requests: list[dict] = Field(min_length=1)


class BatchResponse(BaseModel):
    results: list[NotificationRequestResult]
