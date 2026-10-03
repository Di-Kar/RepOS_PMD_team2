"""Точка входа FastAPI-приложения user_profiles.

Скелет сервиса (S11_T2, issue #109) — без бизнес-логики, CRUD-роуты
добавятся в S11_T3 (docs/user_profiles_contract.md)."""

import logging
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from src.core.config import settings
from src.core.tracer import configure_tracer
from src.db.postgres import close_db

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
    yield
    await close_db()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app)


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok"}


@app.middleware("http")
async def before_request(request: Request, call_next):
    if request.url.path in ("/openapi.json", "/docs", "/redoc", "/health"):
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
