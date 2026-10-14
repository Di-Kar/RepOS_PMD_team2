"""Websocket-эндпоинт для мгновенных уведомлений (S10_T4, issue #97).

Авторизация токеном в query-параметре — в браузерном WebSocket нельзя
выставить произвольный заголовок при подключении. Токен валидируется
вызовом GET /token/verify в auth_service, а не локальным decode JWT:
легковесная проверка без запроса ФИО в user_profiles (ugc_service и
async_api ходят в GET /profile, здесь это не нужно). В отличие от них
фейлимся закрыто — без валидного токена соединение не принимается,
анонимного вебсокета быть не должно (issue #97: «не забывайте про
авторизацию, чтобы предотвратить подключение сторонних пользователей»)."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.auth_client import resolve_user_id
from src.services.websocket_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Websocket"])


@router.websocket("/notifications/ws")
async def notifications_websocket(websocket: WebSocket, token: str) -> None:
    user_id = await resolve_user_id(token)
    if user_id is None:
        # Отклоняем до accept() — Starlette допускает close() без него,
        # это и есть рекомендованный способ отвергнуть подключение по auth.
        await websocket.close(code=4401)
        return

    await websocket.accept()
    manager.register(user_id, websocket)
    try:
        while True:
            # Канал только на доставку сервер -> клиент; receive нужен лишь
            # чтобы дождаться разрыва соединения, входящие данные игнорируем.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(user_id, websocket)
