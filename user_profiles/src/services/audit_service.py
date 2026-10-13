"""Аудит просмотра профилей администратором (docs/user_profiles_contract.md
§3, S11_T10). Fail-open по аналогии с src/services/ugc_client.py: сбой
записи аудита не должен блокировать выдачу профиля администратору — это
не единственный защитный механизм в проекте (как и shared/encryption at
rest, аудит сознательно не доведён до fail-closed комплаенса, см.
user_profiles/readme.md §4)."""

import logging
import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.postgres import AsyncSessionLocal
from src.models.entity import ProfileViewAudit

logger = logging.getLogger(__name__)


class AuditService:
    """Запись и чтение фактов просмотра ФИО/телефона администратором."""

    def __init__(
        self,
        session: AsyncSession,
        audit_session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._session = session
        self._audit_session_factory = audit_session_factory

    async def list_views(
        self, page: int, page_size: int
    ) -> tuple[Sequence[ProfileViewAudit], int]:
        """Страница записей аудита, новые сверху — для страницы «Аудит
        просмотра профилей» в admin_panel (роль audit, S11_T10)."""
        count_stmt = select(func.count()).select_from(ProfileViewAudit)
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = (
            select(ProfileViewAudit)
            .order_by(ProfileViewAudit.viewed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await self._session.execute(stmt)).scalars().all()
        return items, total

    async def record_view(self, admin_email: str, target_user_id: uuid.UUID) -> None:
        # Отдельная сессия: rollback() сессии запроса инвалидирует (expire) уже
        # загруженный в ней profile, и последующий model_validate(profile) в
        # обработчике падает MissingGreenlet (issue #130) — self._session эта
        # запись вообще не трогает.
        try:
            async with self._audit_session_factory() as audit_session:
                audit_session.add(
                    ProfileViewAudit(admin_email=admin_email, target_user_id=target_user_id)
                )
                await audit_session.commit()
        except Exception:  # noqa: BLE001 — любой сбой аудита не должен ронять просмотр
            logger.warning(
                "Не удалось записать аудит просмотра профиля admin_email=%s "
                "target_user_id=%s",
                admin_email,
                target_user_id,
                exc_info=True,
            )
