"""Точка входа FastAPI-приложения ugc_service."""

import logging
from contextlib import asynccontextmanager
from logging import config as logging_config

import sentry_sdk
from api.v1.auth_proxy import router as auth_proxy_router
from api.v1.bookmarks import router as bookmarks_router
from api.v1.likes import router as likes_router
from api.v1.reviews import router as reviews_router
from config import settings
from db.connection import close_db, init_db
from db.init_db import init_cluster
from fastapi import FastAPI, Request
from fastapi.security import OAuth2PasswordBearer

from api.dependencies import get_auth_client
from core.rate_limiter import register_rate_limiter
from core.redis_client import close_redis

from logger import LOGGING

logging_config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)


# ==================================================================== #
#  JWT Bearer security scheme                                            #
# ==================================================================== 
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/auth/login')


# ==================================================================== #
#  Lifespan                                                              #
# ==================================================================== #
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и очистка ресурсов."""
    await init_db()
    await init_cluster()
    yield
    await close_redis()
    await close_db()


# ==================================================================== #
#  FastAPI App                                                         #
# ==================================================================== #
app = FastAPI(
    title=settings.project_name or "ugc_service",
    description='Сервис пользовательского контента: закладки, лайки и рецензии к фильмам.',
    version='1.0.0',
    lifespan=lifespan,
    openapi_url='/openapi.json',
    docs_url='/docs',
    redoc_url='/redoc',
)

register_rate_limiter(app)

# --- ДОБАВЛЕНО: Middleware для извлечения пользователя ---
# Это заполняет request.state.user_id ДО срабатывания лимитера и роутов,
# что позволяет избежать двойного вызова auth_service.
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
            logger.debug(f"Auth middleware skipped (token invalid or auth_service down): {e}")
            
    response = await call_next(request)
    return response


# Кастомизируем OpenAPI schema для авторизации в Swagger
original_openapi = app.openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = original_openapi()

    openapi_schema['components'] = openapi_schema.get('components', {})
    openapi_schema['components']['securitySchemes'] = {
        'BearerAuth': {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'JWT-токен от auth_service. Получите токен через POST /api/v1/auth/login (email + password), затем вставьте его сюда.',
        }
    }

    openapi_schema['security'] = [{'BearerAuth': []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi # type: ignore[method-assign]

app.include_router(auth_proxy_router)
app.include_router(bookmarks_router)
app.include_router(likes_router)
app.include_router(reviews_router)


@app.get('/health', tags=['Health'])
async def health() -> dict:
    return {'status': 'ok'}


if settings.debug:
    @app.get('/api/v1/_sentry_debug')
    async def sentry_debug():
        raise ZeroDivisionError