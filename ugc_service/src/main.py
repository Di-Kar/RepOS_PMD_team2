"""Точка входа FastAPI-приложения ugc_service."""

import logging
from contextlib import asynccontextmanager

from api.v1.auth_proxy import router as auth_proxy_router
from api.v1.bookmarks import router as bookmarks_router
from api.v1.likes import router as likes_router
from api.v1.reviews import router as reviews_router
from config import settings
from db.connection import close_db, init_db
from db.init_db import init_cluster
from fastapi import FastAPI
from fastapi.security import OAuth2PasswordBearer
from logger import LOGGING

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)


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
    await close_db()


# ==================================================================== #
#  FastAPI App                                                           #
# ==================================================================== #

app = FastAPI(
    title=settings.project_name,
    description='Сервис пользовательского контента: закладки, лайки и рецензии к фильмам.',
    version='1.0.0',
    lifespan=lifespan,
    openapi_url='/openapi.json',
    docs_url='/docs',
    redoc_url='/redoc',
)

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


app.openapi = custom_openapi


# Регистрируем роутеры
app.include_router(auth_proxy_router)
app.include_router(bookmarks_router)
app.include_router(likes_router)
app.include_router(reviews_router)


@app.get('/health', tags=['Health'])
async def health() -> dict:
    """Healthcheck для Docker."""
    return {'status': 'ok'}
