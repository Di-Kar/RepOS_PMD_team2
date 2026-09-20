"""Internal (service-to-service) роуты — без JWT конечного пользователя.

Единственный текущий потребитель — notification_worker (S10_T3, issue #96):
из Kafka-сообщения (docs/notification_requests_contract.md §4) ему приходит
только user_id, эндпоинты для людей (GET /profile и т.п.) требуют Bearer-
токен владельца и не подходят. Авторизация — общий X-Internal-Api-Key,
проверяемый verify_internal_api_key (см. src/api/v1/dependencies.py)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import verify_internal_api_key
from src.db.postgres import get_session
from src.models.entity import User
from src.models.schemas import InternalUserProfileResponse
from src.services.auth_service import join_full_name

router = APIRouter(
    prefix="/api/v1/auth/internal",
    tags=["Internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


@router.get("/users/{user_id}", response_model=InternalUserProfileResponse)
async def get_internal_user_profile(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> InternalUserProfileResponse:
    """Профиль пользователя по user_id, для service-to-service обогащения
    (персонализация email/sms/push в notification_worker). Не найден — 404,
    воркер трактует это как постоянную ошибку (DLQ, без ретраев). В отличие
    от get_current_user, деактивированный пользователь (is_active=False) НЕ
    404 — отдаётся как есть, решение "не отправлять" остаётся за вызывающим
    сервисом (см. docs/notification_requests_contract.md)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found", "message": "User not found"},
        )
    return InternalUserProfileResponse(
        id=user.id,
        email=user.login,
        full_name=join_full_name(user),
        is_active=user.is_active,
    )


@router.post("/users/{user_id}/confirm-email", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_user_email(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Проставляет email_confirmed=True.
    Единственный вызывающий — link_shortener_service, при первом валидном
    визите по ссылке purpose=email_confirmation из welcome-письма (см.
    src/services/link_client.py, docs/link_shortener_contract.md). Идемпотентен:
    повторный вызов для уже подтверждённого пользователя — тоже 204, не
    ошибка (несколько кликов по ещё не истёкшей ссылке не должны падать)."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found", "message": "User not found"},
        )
    if not user.email_confirmed:
        user.email_confirmed = True
        await session.commit()
