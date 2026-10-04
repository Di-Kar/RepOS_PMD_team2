"""CRUD-операции и поиск над профилями пользователей."""

import uuid
from typing import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    PhoneAlreadyTakenError,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from src.models.entity import Profile


class ProfileService:
    """Управление профилями (создание, чтение, обновление, удаление, поиск)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, user_id: uuid.UUID, first_name: str, last_name: str, phone: str
    ) -> Profile:
        profile = Profile(
            user_id=user_id, first_name=first_name, last_name=last_name, phone=phone
        )
        self._session.add(profile)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # У Profile два независимых уникальных ограничения (PK user_id и
            # uq_profiles_phone) — sqlstate 23505 один и тот же для обоих,
            # поэтому различаем по имени constraint'а в тексте ошибки (а не
            # только по sqlstate, как в auth_service/role_service.py, где
            # уникальное ограничение одно).
            if "uq_profiles_phone" in str(exc.orig):
                raise PhoneAlreadyTakenError(phone) from exc
            raise ProfileAlreadyExistsError(user_id) from exc
        await self._session.refresh(profile)
        return profile

    async def get_by_id(self, user_id: uuid.UUID) -> Profile:
        profile = await self._session.get(Profile, user_id)
        if profile is None:
            raise ProfileNotFoundError(user_id)
        return profile

    async def update(
        self, user_id: uuid.UUID, first_name: str, last_name: str, phone: str
    ) -> Profile:
        profile = await self.get_by_id(user_id)
        profile.first_name = first_name
        profile.last_name = last_name
        profile.phone = phone
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # PK (user_id) не меняется при update — единственное оставшееся
            # уникальное ограничение, которое может нарушиться, это phone.
            raise PhoneAlreadyTakenError(phone) from exc
        await self._session.refresh(profile)
        return profile

    async def delete(self, user_id: uuid.UUID) -> None:
        profile = await self.get_by_id(user_id)
        await self._session.delete(profile)
        await self._session.commit()

    async def search(
        self, query: str | None, page: int, page_size: int
    ) -> tuple[Sequence[Profile], int]:
        stmt = select(Profile)
        count_stmt = select(func.count()).select_from(Profile)

        if query:
            # Экранируем '%'/'_'/'\\' в пользовательском вводе — иначе они
            # трактуются как метасимволы ILIKE, и поиск по "999_123" или
            # телефону с "%" даёт не те совпадения, что искал вызывающий.
            escaped = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            text_filter = or_(
                Profile.first_name.ilike(pattern, escape="\\"),
                Profile.last_name.ilike(pattern, escape="\\"),
                Profile.first_name.concat(" ")
                .concat(Profile.last_name)
                .ilike(pattern, escape="\\"),
                Profile.phone.ilike(pattern, escape="\\"),
            )
            stmt = stmt.where(text_filter)
            count_stmt = count_stmt.where(text_filter)

        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(Profile.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await self._session.execute(stmt)).scalars().all()
        return items, total
