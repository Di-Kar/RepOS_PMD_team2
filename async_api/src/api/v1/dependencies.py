from typing import Annotated, Optional

from fastapi import Depends, Query, Request

from db.auth_client import AuthServiceClient, UserContext, get_auth_client


class PaginationParams:
    def __init__(
        self,
        page_size: Annotated[
            int,
            Query(
                ge=1,
                le=100,
                description='Количество элементов на странице',
                example=50,
            ),
        ] = 50,
        page_number: Annotated[
            int,
            Query(
                ge=1,
                description='Номер страницы',
                example=1,
            ),
        ] = 1,
    ) -> None:
        self.page_size = page_size
        self.page_number = page_number


async def get_optional_user(
    request: Request,
    auth_client: AuthServiceClient = Depends(get_auth_client),
) -> Optional[UserContext]:
    """Определяет текущего пользователя, спрашивая auth_service по Bearer-токену.

    Ничего не требует и никогда не отклоняет запрос: отсутствие заголовка,
    невалидный/просроченный токен и недоступность самого auth_service
    трактуются как анонимный доступ (None) — каталог фильмов остаётся
    публичным API даже при отказе auth_service.
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.removeprefix('Bearer ').strip()
    return await auth_client.get_current_user(token)
