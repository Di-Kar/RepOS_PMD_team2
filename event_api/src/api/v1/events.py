"""Роуты приёма пользовательских событий — /api/v1/events (FR-22)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.v1.dependencies import verify_api_key
from src.core.config import settings
from src.core.rate_limiter import limiter
from src.models.responses import BatchRequest, BatchResponse, EventResult
from src.services.event_service import process_event

router = APIRouter(prefix="/api/v1/events", tags=["Events"], dependencies=[Depends(verify_api_key)])


@router.post("", response_model=EventResult, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit_events)
async def collect_event(request: Request, payload: dict) -> EventResult:
    """Приём одного события. Тело запроса — событие по контракту
    docs/user_events_contract.md (раздел 2/3). Ответ 202 в т.ч. для
    отклонённых/пропущенных событий: статус результата смотрите в теле
    (status: accepted / skipped_no_consent / rejected) — так клиентский SDK
    не должен разбирать HTTP-коды ошибок отдельно от бизнес-статуса (NFR-3)."""
    return await process_event(payload)


@router.post("/batch", response_model=BatchResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.rate_limit_events)
async def collect_events_batch(request: Request, payload: BatchRequest) -> BatchResponse:
    """Пакетная отправка событий (NFR-5). Каждое событие валидируется и
    публикуется независимо — ошибка в одном не блокирует остальные."""
    if len(payload.events) > settings.batch_max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "batch_too_large",
                "message": f"Batch exceeds max size of {settings.batch_max_size}",
            },
        )
    results = await asyncio.gather(*(process_event(raw) for raw in payload.events))
    return BatchResponse(results=list(results))
