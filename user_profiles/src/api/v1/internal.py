"""Internal (service-to-service) роуты (docs/user_profiles_contract.md §2) —
без JWT конечного пользователя. Авторизация — X-Internal-Api-Key, см.
src/api/v1/dependencies.py:verify_internal_api_key. Потребители:
admin_panel и, после S11_T4, auth_service (резолв ФИО).

Аудит просмотра (контракт §3, S11_T10): опциональный заголовок
X-Admin-Email (см. get_admin_email) — когда присутствует, каждый отданный
профиль логируется в profile_view_audit."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import (
    PaginationParams,
    get_admin_email,
    verify_internal_api_key,
)
from src.core.exceptions import ProfileNotFoundError
from src.db.postgres import get_session
from src.models.schemas import (
    ProfileFullResponse,
    ProfileListResponse,
    ProfileResponse,
    ProfileViewAuditItem,
    ProfileViewAuditListResponse,
)
from src.services import ugc_client
from src.services.audit_service import AuditService
from src.services.profile_service import ProfileService

router = APIRouter(
    prefix="/api/v1/profiles",
    tags=["Internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


@router.get("", response_model=ProfileListResponse)
async def list_profiles(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, description="Поиск по ФИО и телефону"),
    admin_email: str | None = Depends(get_admin_email),
    session: AsyncSession = Depends(get_session),
) -> ProfileListResponse:
    items, total = await ProfileService(session).search(
        search, pagination.page, pagination.page_size
    )
    # Коммитим сразу: иначе на время аудита (своя сессия, см. AuditService)
    # запрос держит два соединения пула одновременно (expire_on_commit=False
    # делает items доступными и после commit).
    await session.commit()
    if admin_email and items:
        # Аудит (контракт §3): по одной строке на каждый профиль, фактически
        # попавший в выданную страницу, а не одна строка на сам факт поиска —
        # иначе не отвечает на "чей профиль смотрели". Один commit на всю
        # страницу (issue #134), а не на каждый профиль отдельно.
        audit = AuditService(session)
        await audit.record_views(admin_email, [item.user_id for item in items])
    return ProfileListResponse(
        items=[ProfileResponse.model_validate(item) for item in items], total=total
    )


@router.get("/audit", response_model=ProfileViewAuditListResponse)
async def list_audit_views(
    pagination: PaginationParams = Depends(),
    session: AsyncSession = Depends(get_session),
) -> ProfileViewAuditListResponse:
    """Страница записей аудита просмотра профилей (контракт §3, S11_T10) —
    для раздела «Аудит просмотра профилей» в admin_panel (роль audit).
    Объявлен раньше /{user_id}, иначе литеральный путь /audit попал бы в
    этот более общий шаблон и упал на валидации user_id как UUID."""
    items, total = await AuditService(session).list_views(
        pagination.page, pagination.page_size
    )
    return ProfileViewAuditListResponse(
        items=[ProfileViewAuditItem.model_validate(item) for item in items],
        total=total,
    )


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_profile_internal(
    user_id: uuid.UUID,
    admin_email: str | None = Depends(get_admin_email),
    session: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    try:
        profile = await ProfileService(session).get_by_id(user_id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "profile_not_found"},
        )
    # Коммитим сразу: иначе на время аудита (своя сессия, см. AuditService)
    # запрос держит два соединения пула одновременно (expire_on_commit=False
    # делает profile доступным и после commit).
    await session.commit()
    if admin_email:
        await AuditService(session).record_view(admin_email, user_id)
    return ProfileResponse.model_validate(profile)


@router.get("/{user_id}/full", response_model=ProfileFullResponse)
async def get_profile_full(
    user_id: uuid.UUID,
    admin_email: str | None = Depends(get_admin_email),
    session: AsyncSession = Depends(get_session),
) -> ProfileFullResponse:
    """Агрегирующая витрина: профиль + закладки/оценки/рецензии из
    ugc_service (docs/user_profiles_contract.md §2). Недоступность
    ugc_service не 500-ит запрос — профиль отдаётся с ugc_available=False
    (см. src/services/ugc_client.py)."""
    try:
        profile = await ProfileService(session).get_by_id(user_id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "profile_not_found"},
        )
    # Коммитим сразу: иначе на время аудита и HTTP-вызова в ugc_service
    # запрос держит соединение пула без необходимости (expire_on_commit=False
    # делает profile доступным и после commit).
    await session.commit()
    if admin_email:
        await AuditService(session).record_view(admin_email, user_id)

    summary = await ugc_client.get_user_ugc_summary(user_id)
    if summary is None:
        return ProfileFullResponse(
            profile=ProfileResponse.model_validate(profile),
            ugc_available=False,
        )
    return ProfileFullResponse(
        profile=ProfileResponse.model_validate(profile),
        ugc_available=True,
        bookmarks=summary.bookmarks,
        ratings=summary.ratings,
        reviews=summary.reviews,
    )
