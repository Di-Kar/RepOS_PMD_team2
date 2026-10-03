"""SQLAlchemy-модель profiles — только каркас таблицы (S11_T2, issue #109).

Бизнес-поля (first_name, last_name, phone — docs/user_profiles_contract.md
§1) добавятся отдельной миграцией в S11_T3. PK — user_id, без суррогатного
id: совпадает с id пользователя в auth_service, но без FK на чужую БД —
только логическая связь (контракт §1)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.postgres import Base


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Profile(user_id={self.user_id})>"
