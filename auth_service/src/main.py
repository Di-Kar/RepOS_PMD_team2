"""Точка входа FastAPI-приложения auth_service."""

import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.sessions import SessionMiddleware

from src.api.v1.auth import router as auth_router
from src.api.v1.idm import router as idm_router
from src.api.v1.oauth import router as oauth_router
from src.core.config import settings
from src.core.rate_limiter import limiter, setup_rate_limit_middleware
from src.core.tracer import configure_tracer
from src.db.postgres import close_db
from src.db.redis_db import close_redis, init_redis

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)


class _HealthcheckAccessLogFilter(logging.Filter):
    """Убирает из access-лога GET /openapi.json (Docker healthcheck, опрос раз в 5с)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/openapi.json" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_HealthcheckAccessLogFilter())


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Включаем трассировку с учётом debug-режима
    debug = getattr(settings, "debug", False)
    configure_tracer(debug=debug)
    
    await init_redis()
    yield
    await close_redis()
    await close_db()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
# Нужен authlib: хранит state/nonce OAuth-флоу между редиректом на Google и callback.
# Секрет отдельный от JWT (settings.secret_key).
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
setup_rate_limit_middleware(app)

app.include_router(auth_router)
app.include_router(idm_router)
app.include_router(oauth_router)


# --- Middleware для X-Request-Id и трассировки ---
@app.middleware('http')
async def before_request(request: Request, call_next):
    # Пропускаем проверку для документации и healthcheck-ручек
    if request.url.path in ['/openapi.json', '/docs', '/redoc', '/health']:
        response = await call_next(request)
        return response
    
    # Генерируем или используем переданный request_id
    request_id = request.headers.get('X-Request-Id')
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())

    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


# Коды ошибок валидации из openapi_auth.yaml: (поле, тип pydantic-ошибки) -> код.
_VALIDATION_ERROR_CODES = {
    ("email", "missing"): "missing_email",
    ("password", "missing"): "missing_password",
    ("password", "string_too_short"): "too_short_password",
    ("full_name", "string_too_long"): "too_long_full_name",
    ("full_name", "string_too_short"): "invalid_full_name",
}


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Спека требует 400 с {error, message, field} вместо стандартного 422 FastAPI."""
    first = exc.errors()[0]
    # loc = ("body", "<имя поля>", ...); для ошибок всего тела поля может не быть.
    field = next((str(part) for part in first["loc"][1:]), None)
    error_type = str(first["type"])  # ← Явно приводим к str
    # Проверяем field на None перед использованием в ключе
    if field is not None:
        error_code = _VALIDATION_ERROR_CODES.get((field, error_type))
        if error_code is None:
            error_code = f"invalid_{field}"
    else:
        error_code = "invalid_validation_error"
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": error_code, "message": first["msg"], "field": field},
    )


if settings.debug:
    @app.get("/api/v1/_sentry_debug")
    async def sentry_debug():
        raise ZeroDivisionError
