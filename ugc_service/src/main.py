"""Точка входа FastAPI-приложения ugc_service."""

import logging
from contextlib import asynccontextmanager
from logging import config as logging_config

import sentry_sdk
from api.v1.auth_proxy import router as auth_proxy_router
from api.v1.bookmarks import router as bookmarks_router
from api.v1.internal import router as internal_router
from api.v1.likes import router as likes_router
from api.v1.reviews import router as reviews_router
from config import settings
from db.connection import close_db, init_db
from db.init_db import init_cluster
from fastapi import FastAPI, Request
from fastapi.security import OAuth2PasswordBearer
from logger import LOGGING

# --- ДОБАВЛЕНО: импорты для rate limiting и Redis ---
from api.dependencies import get_auth_client
from core.rate_limiter import register_rate_limiter
from core.redis_client import close_redis

logging_config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)


# ==================================================================== #
#  JWT Bearer security scheme                                            #
# ==================================================================== #

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login')


# ==================================================================== #
#  Lifespan                                                              #
# ==================================================================== #


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и очистка ресурсов."""
    # Подключение к MongoDB
    await init_db()
    # Инициализация sharding кластера
    await init_cluster()
    yield
    # Очистка
    # --- ДОБАВЛЕНО: закрываем Redis-клиент перед закрытием MongoDB ---
    await close_redis()
    await close_db()


# ==================================================================== #
#  FastAPI App                                                           #
# ==================================================================== #

app = FastAPI(
    title=settings.project_name or 'ugc_service',
    description='Сервис пользовательского контента: закладки, лайки и рецензии к фильмам.',
    version='1.0.0',
    lifespan=lifespan,
    openapi_url='/openapi.json',
    docs_url='/docs',
    redoc_url='/redoc',
)

# --- ДОБАВЛЕНО: Регистрация rate limiter (ДО middleware, чтобы limiter был доступен) ---
register_rate_limiter(app)


# --- ДОБАВЛЕНО: Middleware для извлечения user_id в request.state ---
# Это заполняет request.state.user_id ДО срабатывания limiter'а и роутов,
# что позволяет rate limiter'у работать по user_id, а не по IP.
# Также устраняет двойной вызов auth_service (middleware + Depends).
@app.middleware("http")
async def inject_user_state_middleware(request: Request, call_next):
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            auth_client = await get_auth_client()
            user = await auth_client.get_current_user(token)
            if user and user.user_id:
                request.state.user_id = user.user_id
                request.state.user_name = user.name
        except Exception as e:
            # Если токен невалиден или auth_service недоступен — идём дальше.
            # Rate limiter автоматически упадёт до IP (fallback).
            logger.debug(f"Auth middleware skipped: {e}")

    response = await call_next(request)
    return response


# Кастомизируем OpenAPI schema для авторизации в Swagger
original_openapi = app.openapi


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = original_openapi()

    # Добавляем security scheme
    openapi_schema['components'] = openapi_schema.get('components', {})
    openapi_schema['components']['securitySchemes'] = {
        'BearerAuth': {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'JWT-токен от auth_service. Получите токен через POST /api/v1/auth/login (email + password), затем вставьте его сюда.',
        }
    }

    # Применяем security globally
    openapi_schema['security'] = [{'BearerAuth': []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi   # type: ignore # type: ignore[method-assign]

# Регистрируем роутеры
app.include_router(auth_proxy_router)
app.include_router(bookmarks_router)
app.include_router(likes_router)
app.include_router(reviews_router)
app.include_router(internal_router)


@app.get('/health', tags=['Health'])
async def health() -> dict:
    """Healthcheck для Docker."""
    return {'status': 'ok'}


if settings.debug:

    @app.get('/api/v1/_sentry_debug')
    async def sentry_debug():
        raise ZeroDivisionError