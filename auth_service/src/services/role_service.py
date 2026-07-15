"""CRUD-операции над ролями."""
import uuid
from typing import List, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import RoleAlreadyExistsError, RoleNotFoundError
from src.models.entity import Role


class RoleService:
    """Управление ролями (создание, чтение, обновление, удаление)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, description: str | None, permissions: List[str]) -> Role:
        role = Role(name=name, description=description, permissions=permissions)
        self._session.add(role)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise RoleAlreadyExistsError(name)
        await self._session.refresh(role)
        return role

    async def list_all(self) -> Sequence[Role]:
        result = await self._session.execute(select(Role).order_by(Role.created_at))
        return result.scalars().all()

    async def get_by_id(self, role_id: uuid.UUID) -> Role:
        role = await self._session.get(Role, role_id)
        if role is None:
            raise RoleNotFoundError(role_id)
        return role

    async def update(
        self,
        role_id: uuid.UUID,
        name: str | None,
        description: str | None,
        permissions: List[str] | None,
    ) -> Role:
        role = await self.get_by_id(role_id)
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permissions is not None:
            role.permissions = permissions
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise RoleAlreadyExistsError(name)
        await self._session.refresh(role)
        return role

    async def delete(self, role_id: uuid.UUID) -> None:
        role = await self.get_by_id(role_id)
        await self._session.delete(role)
        await self._session.commit()
