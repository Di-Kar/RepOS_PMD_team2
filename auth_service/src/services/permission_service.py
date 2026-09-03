"""Назначение/снятие ролей и проверка прав пользователя (с кэшированием в Redis)."""

import json
import uuid
from typing import List, Set, Tuple

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    RoleAlreadyAssignedError,
    RoleNotAssignedError,
    RoleNotFoundError,
    UserNotFoundError,
)
from src.models.entity import Role, User, UserRole

PERMISSIONS_CACHE_TTL_SECONDS = 300
PERMISSIONS_CACHE_KEY = "idm:permissions:{user_id}"


class PermissionService:
    """Управление назначением ролей и проверкой прав."""

    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    async def _get_user(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    async def _get_role(self, role_id: uuid.UUID) -> Role:
        role = await self._session.get(Role, role_id)
        if role is None:
            raise RoleNotFoundError(role_id)
        return role

    async def assign_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> Role:
        await self._get_user(user_id)
        role = await self._get_role(role_id)

        user_role = UserRole(user_id=user_id, role_id=role_id)
        self._session.add(user_role)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise RoleAlreadyAssignedError((user_id, role_id))

        await self._invalidate_cache(user_id)
        return role

    async def remove_role(self, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        await self._get_user(user_id)
        await self._get_role(role_id)

        result = await self._session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id
            )
        )
        user_role = result.scalar_one_or_none()
        if user_role is None:
            raise RoleNotAssignedError((user_id, role_id))

        await self._session.delete(user_role)
        await self._session.commit()
        await self._invalidate_cache(user_id)

    async def get_user_permissions(self, user_id: uuid.UUID) -> Set[str]:
        await self._get_user(user_id)

        cache_key = PERMISSIONS_CACHE_KEY.format(user_id=user_id)
        cached = await self._redis.get(cache_key)
        if cached is not None:
            return set(json.loads(cached))

        # Прямой join вместо обхода User.user_roles: relationship с lazy="selectin"
        # мог быть уже закэширован пустым (например, если пользователь был прочитан
        # до назначения роли в той же сессии), а expire_on_commit=False не сбрасывает
        # такой кэш сам по себе.
        result = await self._session.execute(
            select(Role.permissions)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )

        permissions: Set[str] = set()
        for role_permissions in result.scalars():
            permissions.update(role_permissions)

        await self._redis.set(
            cache_key, json.dumps(sorted(permissions)), ex=PERMISSIONS_CACHE_TTL_SECONDS
        )
        return permissions

    async def _invalidate_cache(self, user_id: uuid.UUID) -> None:
        await self._redis.delete(PERMISSIONS_CACHE_KEY.format(user_id=user_id))

    async def check_permission(
        self, user_id: uuid.UUID, permission: str
    ) -> Tuple[bool, List[str], List[str]]:
        user = await self._get_user(user_id)
        granted = await self.get_user_permissions(user_id)

        # Суперпользователю разрешены любые действия в обход назначенных ролей.
        has_permission = user.is_superuser or permission in granted
        missing = [] if has_permission else [permission]
        return has_permission, sorted(granted), missing
