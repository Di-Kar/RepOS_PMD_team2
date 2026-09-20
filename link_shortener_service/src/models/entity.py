"""SQLAlchemy-модель short_links — универсальный сократитель ссылок.
Сейчас используется purpose='email_confirmation' (auth_service), поле
оставлено расширяемым под будущие сообщения/уведомления
(docs/link_shortener_contract.md)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.postgres import Base

PURPOSE_GENERIC = "generic"
PURPOSE_EMAIL_CONFIRMATION = "email_confirmation"


class ShortLink(Base):
    """Одна строка — одна короткая ссылка. confirmed_at (не отдельный
    boolean) одновременно хранит и факт, и момент первого успешного
    срабатывания side-effect'а — делает повторные клики по valid-ссылке
    идемпотентными без дополнительного состояния."""

    __tablename__ = "short_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    redirect_url: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(50), nullable=False, default=PURPOSE_GENERIC, server_default=PURPOSE_GENERIC
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    visit_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    first_visited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_visited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_service: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ShortLink(code={self.code}, purpose={self.purpose})>"
