import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    RoleAlreadyAssignedError,
    RoleNotAssignedError,
    RoleNotFoundError,
    UserNotFoundError,
)
from src.models.entity import Role, User
from src.services.permission_service import PermissionService


class TestAssignRole:
    async def test_assign_role(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        role = await service.assign_role(sample_user.id, sample_role.id)

        assert role.id == sample_role.id

    async def test_assign_role_twice_raises(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)

        with pytest.raises(RoleAlreadyAssignedError):
            await service.assign_role(sample_user.id, sample_role.id)

    async def test_assign_role_unknown_user_raises(
        self, db_session: AsyncSession, redis_client: Redis, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        with pytest.raises(UserNotFoundError):
            await service.assign_role(uuid.uuid4(), sample_role.id)

    async def test_assign_unknown_role_raises(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User
    ):
        service = PermissionService(db_session, redis_client)
        with pytest.raises(RoleNotFoundError):
            await service.assign_role(sample_user.id, uuid.uuid4())


class TestRemoveRole:
    async def test_remove_role(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)
        await service.remove_role(sample_user.id, sample_role.id)

        permissions = await service.get_user_permissions(sample_user.id)
        assert permissions == set()

    async def test_remove_not_assigned_raises(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        with pytest.raises(RoleNotAssignedError):
            await service.remove_role(sample_user.id, sample_role.id)


class TestCheckPermission:
    async def test_has_permission_via_role(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)

        has_permission, granted, missing = await service.check_permission(sample_user.id, "video:watch")

        assert has_permission is True
        assert "video:watch" in granted
        assert missing == []

    async def test_missing_permission(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)

        has_permission, _, missing = await service.check_permission(sample_user.id, "admin:delete")

        assert has_permission is False
        assert missing == ["admin:delete"]

    async def test_superuser_bypasses_roles(
        self, db_session: AsyncSession, redis_client: Redis, sample_superuser: User
    ):
        service = PermissionService(db_session, redis_client)
        has_permission, _, missing = await service.check_permission(sample_superuser.id, "admin:delete")

        assert has_permission is True
        assert missing == []

    async def test_permissions_are_cached(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)
        await service.get_user_permissions(sample_user.id)

        cached = await redis_client.get(f"idm:permissions:{sample_user.id}")
        assert cached is not None

    async def test_cache_invalidated_on_role_removal(
        self, db_session: AsyncSession, redis_client: Redis, sample_user: User, sample_role: Role
    ):
        service = PermissionService(db_session, redis_client)
        await service.assign_role(sample_user.id, sample_role.id)
        await service.get_user_permissions(sample_user.id)

        await service.remove_role(sample_user.id, sample_role.id)

        cached = await redis_client.get(f"idm:permissions:{sample_user.id}")
        assert cached is None
