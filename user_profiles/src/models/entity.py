"""SQLAlchemy-модель profiles (docs/user_profiles_contract.md §1).

PK — user_id, без суррогатного id: совпадает с id пользователя в
auth_service, но без FK на чужую БД — только логическая связь (контракт
§1). phone_verified всегда False — SMS-подтверждение исключено из скоупа
(FR1.4), колонка зарезервирована на будущее и не выставляется через API."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.postgres import Base


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("phone", name="uq_profiles_phone"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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


class ProfileViewAudit(Base):
    """Факт просмотра администратором чувствительных данных профиля
    (ФИО, телефон) — docs/user_profiles_contract.md §3, S11_T10. Без FK на
    profiles.user_id: запись аудита должна переживать удаление профиля
    (право на забвение, FR1.5), в отличие от login_history в auth_service,
    где каскадное удаление уместно."""

    __tablename__ = "profile_view_audit"
    __table_args__ = (
        Index("idx_profile_view_audit_target_user_id", "target_user_id"),
        Index("idx_profile_view_audit_viewed_at", "viewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ProfileViewAudit(admin_email={self.admin_email}, "
            f"target_user_id={self.target_user_id})>"
        )
