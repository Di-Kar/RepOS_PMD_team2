"""Роуты управления ролями и правами (RBAC) — /api/v1/idm."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import get_current_user, require_superuser
from src.core.exceptions import (
    RoleAlreadyAssignedError,
    RoleAlreadyExistsError,
    RoleNotAssignedError,
    RoleNotFoundError,
    UserNotFoundError,
)
from src.db.postgres import get_session
from src.db.redis_db import get_redis
from src.models.entity import User
from src.models.schemas import (
    PermissionCheckRequest,
    PermissionCheckResponse,
    RoleCreate,
    RoleResponse,
    RolesListResponse,
    RoleUpdate,
    UserRoleRequest,
)
from src.services.permission_service import PermissionService
from src.services.role_service import RoleService

router = APIRouter(prefix="/api/v1/idm")


@router.post(
    "/roles",
    tags=["Roles"],
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_role(
    payload: RoleCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_superuser),
) -> RoleResponse:
    service = RoleService(session)
    try:
        role = await service.create(payload.name, payload.description, payload.permissions)
    except RoleAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "role_name_taken", "message": "Role with this name already exists", "field": "name"},
        )
    return role


@router.get("/roles", tags=["Roles"], response_model=RolesListResponse)
async def list_roles(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
) -> RolesListResponse:
    service = RoleService(session)
    roles = await service.list_all()
    return RolesListResponse(items=list(roles), total=len(roles))


@router.put("/roles/{role_id}", tags=["Roles"], response_model=RoleResponse)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_superuser),
) -> RoleResponse:
    service = RoleService(session)
    try:
        role = await service.update(role_id, payload.name, payload.description, payload.permissions)
    except RoleNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    except RoleAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "role_name_taken", "message": "Role with this name already exists", "field": "name"},
        )
    return role


@router.delete("/roles/{role_id}", tags=["Roles"], status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_superuser),
) -> None:
    service = RoleService(session)
    try:
        await service.delete(role_id)
    except RoleNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")


@router.post("/users/{user_id}/roles", tags=["Permissions"], response_model=RoleResponse)
async def assign_role(
    user_id: uuid.UUID,
    payload: UserRoleRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _: User = Depends(require_superuser),
) -> RoleResponse:
    service = PermissionService(session, redis)
    try:
        role = await service.assign_role(user_id, payload.role_id)
    except (UserNotFoundError, RoleNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User or role not found")
    except RoleAlreadyAssignedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "role_already_assigned", "message": "Role is already assigned to this user"},
        )
    return role


@router.delete(
    "/users/{user_id}/roles/{role_id}", tags=["Permissions"], status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    _: User = Depends(require_superuser),
) -> None:
    service = PermissionService(session, redis)
    try:
        await service.remove_role(user_id, role_id)
    except (UserNotFoundError, RoleNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User or role not found")
    except RoleNotAssignedError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role was not assigned to this user")


@router.post(
    "/users/{user_id}/permissions/check", tags=["Permissions"], response_model=PermissionCheckResponse
)
async def check_permission(
    user_id: uuid.UUID,
    payload: PermissionCheckRequest,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    current_user: User = Depends(get_current_user),
) -> PermissionCheckResponse:
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "required_scope_missing",
                "message": "Only a superuser can check another user's permissions",
            },
        )

    service = PermissionService(session, redis)
    try:
        has_permission, granted, missing = await service.check_permission(user_id, payload.permission)
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return PermissionCheckResponse(
        has_permission=has_permission, granted_permissions=granted, missing_permissions=missing
    )
