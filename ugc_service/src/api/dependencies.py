"""Зависимости API: аутентификация, пагинация и валидация ObjectId."""

from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from config import settings
from fastapi import Depends, HTTPException, Query, Request, status
from httpx import AsyncClient, HTTPError


def _validate_object_id(review_id: str) -> ObjectId:
    """Валидировать и преобразовать строку в ObjectId."""
    try:
        return ObjectId(review_id)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Невалидный ObjectId: {review_id}',
        )


def get_validated_object_id(review_id: str) -> ObjectId:
    """FastAPI-зависимость для валидации ObjectId в path-параметрах.

    Возвращает ObjectId при валидном значении.
    Бросает HTTPException(422) при невалидном формате.
    Срабатывает ДО проверки авторизации.

    FastAPI автоматически подставит значение path-параметра
    по имени аргумента (review_id).
    """
    return _validate_object_id(review_id)


class PaginationParams:
    """Параметры пагинации."""

    def __init__(
        self,
        page_number: Annotated[
            int,
            Query(ge=1, description='Номер страницы', example=1),
        ] = 1,
        page_size: Annotated[
            int,
            Query(ge=1, le=100, description='Элементов на странице', example=20),
        ] = 20,
    ) -> None:
        self.page_number = page_number
        self.page_size = page_size


class UserContext:
    """Контекст текущего пользователя."""

    def __init__(self, user_id: str, name: str):
        self.user_id = user_id
        self.name = name


class AuthServiceClient:
    """Клиент для вызова auth_service."""

    def __init__(
        self,
        base_url: str = settings.auth_service_url,
        timeout: float = settings.auth_request_timeout,
    ):
        self.base_url = base_url
        self.timeout = timeout

    async def get_current_user(self, token: str) -> UserContext | None:
        """Получить текущего пользователя по Bearer-токену."""
        try:
            async with AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f'{self.base_url}/profile',
                    headers={'Authorization': f'Bearer {token}'},
                )
                if response.status_code == 200:
                    data = response.json()
                    return UserContext(
                        user_id=data.get('id', ''),
                        name=data.get('full_name', ''),
                    )
        except HTTPError:
            pass
        return None


_auth_client: AuthServiceClient | None = None


async def get_auth_client() -> AuthServiceClient:
    """Получить клиент auth_service (синглтон)."""
    global _auth_client
    if _auth_client is None:
        _auth_client = AuthServiceClient()
    return _auth_client


async def get_optional_user(
    request: Request,
    auth_client: AuthServiceClient = Depends(get_auth_client),
) -> UserContext | None:
    """Определить текущего пользователя по Bearer-токену.

    Ничего не требует и никогда не отклоняет запрос: отсутствие заголовка,
    невалидный/просроченный токен и недоступность auth_service трактуются
    как анонимный доступ (None).
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.removeprefix('Bearer ').strip()
    return await auth_client.get_current_user(token)
