"""SQLAlchemy-модель лога отправленных в Kafka заявок
(docs/notification_requests_contract.md §9)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.postgres import Base

# Статусы, которые проставляет сам notification_api сразу после попытки
# публикации в Kafka. Дальнейшие статусы (доставлено/прочитано/ошибка
# доставки и т.п.) проставляет notification_worker поверх этой же строки —
# поэтому status намеренно не Postgres ENUM, а обычная строка: расширение
# набора значений воркером не требует миграции в notification_api.
STATUS_KAFKA_PUBLISHED = "kafka_published"
STATUS_KAFKA_PUBLISH_FAILED = "kafka_publish_failed"


class NotificationLog(Base):
    """Одна строка на notification_id (т.е. на получателя после фан-аута) —
    тот же ключ, что и в сообщении Kafka, по нему notification_worker будет
    обновлять status."""

    __tablename__ = "notification_log"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_service: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=STATUS_KAFKA_PUBLISHED, index=True
    )
    # Автообновление при любом UPDATE строки — это может быть UPDATE не только
    # из этого сервиса, но и от notification_worker (§9), поэтому нужен
    # именно DB-триггер (см. миграцию), а не Python-side onupdate: тот сработал
    # бы только для UPDATE, выполненных через SQLAlchemy этого кодабейза.
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationLog(notification_id={self.notification_id}, "
            f"status={self.status})>"
        )
