import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import RoleAlreadyExistsError, RoleNotFoundError
from src.models.entity import Role
from src.services.role_service import RoleService


class TestRoleServiceCreate:
    async def test_create_role(self, db_session: AsyncSession):
        service = RoleService(db_session)
        role = await service.create("subscriber", "Paid subscriber", ["video:watch"])

        assert role.id is not None
        assert role.name == "subscriber"
        assert role.permissions == ["video:watch"]

    async def test_create_duplicate_role_name_raises(self, db_session: AsyncSession, sample_role: Role):
        service = RoleService(db_session)
        with pytest.raises(RoleAlreadyExistsError):
            await service.create(sample_role.name, None, [])


class TestRoleServiceRead:
    async def test_list_all(self, db_session: AsyncSession, sample_role: Role):
        service = RoleService(db_session)
        roles = await service.list_all()

        assert any(r.id == sample_role.id for r in roles)

    async def test_get_by_id(self, db_session: AsyncSession, sample_role: Role):
        service = RoleService(db_session)
        role = await service.get_by_id(sample_role.id)

        assert role.id == sample_role.id

    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        service = RoleService(db_session)
        with pytest.raises(RoleNotFoundError):
            await service.get_by_id(uuid.uuid4())


class TestRoleServiceUpdate:
    async def test_update_permissions(self, db_session: AsyncSession, sample_role: Role):
        service = RoleService(db_session)
        updated = await service.update(sample_role.id, None, None, ["video:watch", "video:watch:new"])

        assert updated.permissions == ["video:watch", "video:watch:new"]

    async def test_update_not_found(self, db_session: AsyncSession):
        service = RoleService(db_session)
        with pytest.raises(RoleNotFoundError):
            await service.update(uuid.uuid4(), "new_name", None, None)


class TestRoleServiceDelete:
    async def test_delete_role(self, db_session: AsyncSession, sample_role: Role):
        service = RoleService(db_session)
        await service.delete(sample_role.id)

        with pytest.raises(RoleNotFoundError):
            await service.get_by_id(sample_role.id)

    async def test_delete_not_found(self, db_session: AsyncSession):
        service = RoleService(db_session)
        with pytest.raises(RoleNotFoundError):
            await service.delete(uuid.uuid4())
