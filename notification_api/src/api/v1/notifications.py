"""Роуты приёма заявок на уведомления — /api/v1/notifications
(docs/notification_requests_contract.md §2)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.v1.dependencies import verify_api_key
from src.core.config import settings
from src.core.rate_limiter import limiter
from src.models.responses import BatchRequest, BatchResponse, NotificationRequestResult
from src.services.notification_service import process_notification_request

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"],
    dependencies=[Depends(verify_api_key)],
)


@router.post(
    "", response_model=NotificationRequestResult, status_code=status.HTTP_202_ACCEPTED
)
@limiter.limit(settings.rate_limit_notifications)
async def create_notification(
    request: Request, payload: dict
) -> NotificationRequestResult:
    """Приём одной заявки, возможно на нескольких получателей одного
    шаблона/сообщения (тело — по контракту §3). Отвечает 202 всегда, в т.ч.
    для отклонённых заявок/получателей — статус смотрите в теле (§2)."""
    return await process_notification_request(payload)


@router.post(
    "/batch", response_model=BatchResponse, status_code=status.HTTP_202_ACCEPTED
)
@limiter.limit(settings.rate_limit_notifications)
async def create_notifications_batch(
    request: Request, payload: BatchRequest
) -> BatchResponse:
    """Пакетная отправка независимых заявок. Каждая валидируется и
    разворачивается независимо — ошибка в одной не блокирует остальные."""
    if len(payload.requests) > settings.batch_max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "batch_too_large",
                "message": f"Batch exceeds max size of {settings.batch_max_size}",
            },
        )
    results = await asyncio.gather(
        *(process_notification_request(raw) for raw in payload.requests)
    )
    return BatchResponse(results=list(results))
