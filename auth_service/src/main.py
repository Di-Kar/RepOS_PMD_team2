"""Точка входа FastAPI-приложения auth_service."""
from fastapi import FastAPI

from src.api.v1.idm import router as idm_router
from src.core.config import settings

app = FastAPI(title=settings.app_name)

app.include_router(idm_router)

# TODO: подключить роутер /api/v1/auth, когда будет готова аутентификация.
