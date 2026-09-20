"""Точка входа FastAPI-приложения link_shortener_service."""

import logging
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.v1.links import router as links_router
from src.api.v1.redirect import router as redirect_router
from src.core.config import settings
from src.core.rate_limiter import limiter
from src.core.tracer import configure_tracer
from src.db.postgres import close_db
from src.services.auth_client import close_auth_client, init_auth_client

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)


class _HealthcheckAccessLogFilter(logging.Filter):
    """Убирает из access-лога GET /health (Docker healthcheck, опрос раз в 5с)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_HealthcheckAccessLogFilter())


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_tracer(debug=settings.debug)
    await init_auth_client()
    yield
    await close_auth_client()
    await close_db()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(links_router)
app.include_router(redirect_router)


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}


@app.middleware("http")
async def before_request(request: Request, call_next):
    # /r/* отдаёт HTML/редирект, не JSON — не размечаем его X-Request-Id,
    # чтобы не трогать ответ RedirectResponse/HTMLResponse без нужды.
    if request.url.path in ("/openapi.json", "/docs", "/redoc", "/health") or (
        request.url.path.startswith("/r/")
    ):
        return await call_next(request)

    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    first = exc.errors()[0]
    field = next((str(part) for part in first["loc"][1:]), None)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "validation_error", "message": first["msg"], "field": field},
    )


if settings.debug:

    @app.get("/api/v1/_sentry_debug")
    async def sentry_debug():
        raise ZeroDivisionError
