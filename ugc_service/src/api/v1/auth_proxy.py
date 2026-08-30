"""API endpoints для авторизации (прокси к auth_service)."""

import logging

from config import settings
from fastapi import APIRouter, HTTPException
from httpx import AsyncClient, HTTPError
from pydantic import BaseModel, Field


router = APIRouter(prefix='/api/v1/auth', tags=['Авторизация'])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    """Запрос на вход."""

    email: str = Field(
        ...,
        example='test_e2e@example.com',
        description='Email пользователя (логин)',
    )
    password: str = Field(
        ...,
        min_length=8,
        example='TestPass123!',
        description='Пароль пользователя',
    )


class TokenResponse(BaseModel):
    """Ответ с токеном авторизации."""

    access_token: str
    token_type: str = 'bearer'


@router.post(
    '/login',
    response_model=TokenResponse,
    summary='Получить JWT-токен',
    description='Авторизуйтесь через auth_service и получите JWT-токен для доступа к API.',
    openapi_extra={
        'x-codeSamples': [
            {
                'lang': 'curl',
                'source': "curl -X POST 'http://localhost:8003/api/v1/auth/login' -H 'Content-Type: application/json' -d '{\"email\": \"test_e2e@example.com\", \"password\": \"TestPass123!\"}'",
            }
        ],
    },
)
async def login(payload: LoginRequest):
    """Получить JWT-токен через auth_service."""
    try:
        async with AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f'{settings.auth_service_url}/login',
                json={'email': payload.email, 'password': payload.password},
            )

            if response.status_code == 200:
                data = response.json()
                return TokenResponse(
                    access_token=data.get('access_token', ''),
                    token_type=data.get('token_type', 'bearer'),
                )

            # Проксируем ошибку от auth_service
            raise HTTPException(
                status_code=response.status_code,
                detail=response.json().get('detail', 'Неверный email или пароль'),
            )
    except HTTPError as e:
        logger.error('Ошибка авторизации: %s', e)
        raise HTTPException(
            status_code=502,
            detail='Не удалось подключиться к auth_service',
        )
