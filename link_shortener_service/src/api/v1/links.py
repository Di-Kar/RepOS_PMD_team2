"""Роут создания коротких ссылок — POST /api/v1/links
(docs/link_shortener_contract.md §1)."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.dependencies import verify_api_key
from src.core.config import settings
from src.core.rate_limiter import limiter
from src.db.postgres import get_session
from src.models.schemas import CreateLinkRequest, CreateLinkResponse
from src.services.link_service import create_short_link

router = APIRouter(
    prefix="/api/v1/links", tags=["Links"], dependencies=[Depends(verify_api_key)]
)


@router.post("", response_model=CreateLinkResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_create)
async def create_link(
    request: Request,
    payload: CreateLinkRequest,
    session: AsyncSession = Depends(get_session),
) -> CreateLinkResponse:
    link = await create_short_link(session, payload)
    return CreateLinkResponse(
        code=link.code,
        short_url=f"{settings.public_base_url}/r/{link.code}",
        expires_at=link.expires_at,
    )
