"""Бизнес-логика short_links: создание короткого кода с retry на коллизию,
атомарный визит по коду (docs/link_shortener_contract.md §4).

Визит намеренно не держит блокировку Postgres-строки через границу исходящего
HTTP-вызова к auth_service (риск исчерпать connection pool при подвисшем
auth_service). Вместо этого корректность при параллельных визитах по одному
коду обеспечивается идемпотентностью на стороне владельца эффекта:
auth_service/internal confirm-email уже идемпотентен ("уже True -> просто
204"), а confirmed_at здесь выставляется через COALESCE — при гонке оба
конкурентных визита могут дёрнуть confirm-email, но это избыточно, не
опасно."""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.core.config import settings
from src.models.entity import PURPOSE_EMAIL_CONFIRMATION, ShortLink
from src.models.schemas import CreateLinkRequest
from src.services.auth_client import AuthServiceUnavailableError
from src.services.auth_client import confirm_email as auth_confirm_email

logger = logging.getLogger(__name__)


def _generate_code() -> str:
    return "".join(
        secrets.choice(settings.code_alphabet) for _ in range(settings.code_length)
    )


async def create_short_link(
    session: AsyncSession, payload: CreateLinkRequest
) -> ShortLink:
    ttl = payload.ttl_seconds or settings.default_ttl_seconds
    ttl = min(ttl, settings.max_ttl_seconds)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    last_error: Exception | None = None
    for attempt in range(settings.code_generation_max_attempts):
        code = _generate_code()
        link = ShortLink(
            code=code,
            owner_user_id=payload.owner_user_id,
            redirect_url=payload.redirect_url,
            purpose=payload.purpose,
            expires_at=expires_at,
            source_service=payload.source_service,
        )
        session.add(link)
        try:
            await session.commit()
            await session.refresh(link)
            return link
        except IntegrityError as exc:
            await session.rollback()
            last_error = exc
            logger.warning("code collision on attempt %s, retrying", attempt + 1)
    raise RuntimeError(
        "failed to generate a unique short code after max attempts"
    ) from last_error


@dataclass
class VisitOutcome:
    found: bool
    redirect_url: str | None = None


async def visit_short_link(session: AsyncSession, code: str) -> VisitOutcome:
    # Шаг A: атомарный инкремент визита + проверка срока действия одной
    # UPDATE ... RETURNING — 0 строк значит "не найдено или истекло", и мы
    # намеренно не различаем эти два случая снаружи (см. контракт §2).
    stmt = (
        update(ShortLink)
        .where(ShortLink.code == code, ShortLink.expires_at > func.now())
        .values(
            visit_count=ShortLink.visit_count + 1,
            last_visited_at=func.now(),
            first_visited_at=func.coalesce(ShortLink.first_visited_at, func.now()),
        )
        .returning(
            ShortLink.id,
            ShortLink.redirect_url,
            ShortLink.purpose,
            ShortLink.confirmed_at,
            ShortLink.owner_user_id,
        )
    )
    row = (await session.execute(stmt)).first()
    await session.commit()
    if row is None:
        return VisitOutcome(found=False)

    if (
        row.purpose == PURPOSE_EMAIL_CONFIRMATION
        and row.confirmed_at is None
        and row.owner_user_id is not None
    ):
        try:
            await auth_confirm_email(row.owner_user_id)
        except AuthServiceUnavailableError:
            # Визит уже посчитан (это факт клика, а не факт успешного
            # бизнес-эффекта) — но подтверждения не было, редиректить нельзя.
            raise
        await session.execute(
            update(ShortLink)
            .where(ShortLink.id == row.id)
            .values(confirmed_at=func.coalesce(ShortLink.confirmed_at, func.now()))
        )
        await session.commit()

    return VisitOutcome(found=True, redirect_url=row.redirect_url)
