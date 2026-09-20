"""Публичный редирект-эндпоинт GET /r/{code} — без авторизации, открывается
кликом по ссылке в письме (docs/link_shortener_contract.md §2). CORS тут не
при чём: это top-level навигация браузера, не fetch/XHR."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.rate_limiter import limiter
from src.db.postgres import get_session
from src.pages import NOT_FOUND_HTML, SERVICE_UNAVAILABLE_HTML
from src.services.auth_client import AuthServiceUnavailableError
from src.services.link_service import visit_short_link

router = APIRouter(tags=["Redirect"])


@router.get("/r/{code}")
@limiter.limit(settings.rate_limit_redirect)
async def redirect(
    code: str, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        outcome = await visit_short_link(session, code)
    except AuthServiceUnavailableError:
        return HTMLResponse(content=SERVICE_UNAVAILABLE_HTML, status_code=503)

    if not outcome.found:
        return HTMLResponse(content=NOT_FOUND_HTML, status_code=404)

    return RedirectResponse(url=outcome.redirect_url, status_code=302)
