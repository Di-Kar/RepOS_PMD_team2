"""Internal (service-to-service) роуты (docs/user_profiles_contract.md §2) —
без JWT конечного пользователя. Авторизация — X-Internal-Api-Key, см.
src/api/v1/dependencies.py:verify_internal_api_key. Потребители:
admin_panel и, после S11_T4, auth_service (резолв ФИО)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import PaginationParams, verify_internal_api_key
from src.core.exceptions import ProfileNotFoundError
from src.db.postgres import get_session
from src.models.schemas import ProfileListResponse, ProfileResponse
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
    session: AsyncSession = Depends(get_session),
) -> ProfileListResponse:
    items, total = await ProfileService(session).search(
        search, pagination.page, pagination.page_size
    )
    return ProfileListResponse(
        items=[ProfileResponse.model_validate(item) for item in items], total=total
    )


@router.get("/{user_id}", response_model=ProfileResponse)
async def get_profile_internal(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    try:
        profile = await ProfileService(session).get_by_id(user_id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "profile_not_found"},
        )
    return ProfileResponse.model_validate(profile)
