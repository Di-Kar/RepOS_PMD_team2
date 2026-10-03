"""Self-service эндпоинты /api/v1/profiles/me (docs/user_profiles_contract.md
§1) — авторизация Bearer JWT через auth_service, без анонимного фолбэка."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import get_current_user_id
from src.core.exceptions import (
    PhoneAlreadyTakenError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from src.db.postgres import get_session
from src.models.schemas import (
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)
from src.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/profiles", tags=["Profiles"])


@router.post("/me", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_my_profile(
    body: ProfileCreateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    try:
        profile = await ProfileService(session).create(
            user_id, body.first_name, body.last_name, body.phone
        )
    except ProfileAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "profile_already_exists"},
        )
    except PhoneAlreadyTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "phone_already_taken"},
        )
    return ProfileResponse.model_validate(profile)


@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(
    user_id: uuid.UUID = Depends(get_current_user_id),
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


@router.put("/me", response_model=ProfileResponse)
async def update_my_profile(
    body: ProfileUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> ProfileResponse:
    try:
        profile = await ProfileService(session).update(
            user_id, body.first_name, body.last_name, body.phone
        )
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "profile_not_found"},
        )
    except PhoneAlreadyTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "phone_already_taken"},
        )
    return ProfileResponse.model_validate(profile)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_profile(
    user_id: uuid.UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await ProfileService(session).delete(user_id)
    except ProfileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "profile_not_found"},
        )
