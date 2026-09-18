"""Реестр открытых websocket-соединений (S10_T4, issue #97).

Один пользователь может держать несколько соединений (вкладки/устройства) —
рассылаем во все. Реестр живёт только в памяти этого инстанса: без Redis
pub/sub между репликами — сейчас notification_api в docker-compose
запускается в одном экземпляре, горизонтальное масштабирование не
поддерживается."""

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    def register(self, user_id: str, websocket: WebSocket) -> None:
        self._connections[user_id].add(websocket)

    def unregister(self, user_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(user_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            del self._connections[user_id]

    async def send_to_user(self, user_id: str, payload: dict) -> bool:
        """Отправляет payload во все открытые соединения пользователя.
        Возвращает True, если было хотя бы одно соединение (best-effort:
        офлайн-получателю сообщение просто теряется, см. §8 контракта)."""
        connections = list(self._connections.get(user_id, ()))
        if not connections:
            return False
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception as exc:
                logger.warning(f"Failed to push websocket notification to {user_id}: {exc}")
        return True


manager = WebSocketManager()
