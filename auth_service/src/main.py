"""Точка входа FastAPI-приложения auth_service."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.v1.auth import router as auth_router
from src.api.v1.idm import router as idm_router
from src.api.v1.oauth import router as oauth_router
from src.core.config import settings
from src.db.postgres import close_db
from src.db.redis_db import close_redis, init_redis
from src.core.rate_limiter import limiter, setup_rate_limit_middleware

# --- OpenTelemetry (Jaeger) setup ---
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def configure_tracer() -> None:
    # Настройка ресурса
    resource = Resource.create(attributes={
        SERVICE_NAME: "auth_service"
    }) 

    # Настройка экспортера Jaeger (используется UDP по умолчанию на порт 6831)
    jaeger_exporter = OTLPSpanExporter(
        endpoint=settings.jaeger_endpoint,
    )
    # Установка провайдера трассировки
    trace.set_tracer_provider(TracerProvider(resource=resource))
    tracer_provider = trace.get_tracer_provider()
    tracer_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
    # Включение TraceContextTextMapPropagator для поддержки w3c trace-context
    set_global_textmap(TraceContextTextMapPropagator())
    # Чтобы видеть трейсы в консоли
    trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))


class _HealthcheckAccessLogFilter(logging.Filter):
    """Убирает из access-лога GET /openapi.json (Docker healthcheck, опрос раз в 5с)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/openapi.json" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_HealthcheckAccessLogFilter())


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_redis()
    yield
    await close_redis()
    await close_db()


configure_tracer()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

FastAPIInstrumentor.instrument_app(app) 

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
# Нужен authlib: хранит state/nonce OAuth-флоу между редиректом на Google и callback.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
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
    error_type = first["type"]

    error_code = _VALIDATION_ERROR_CODES.get((field, error_type))
    if error_code is None:
        error_code = f"invalid_{field}" if field else "validation_error"

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": error_code, "message": first["msg"], "field": field},
    )