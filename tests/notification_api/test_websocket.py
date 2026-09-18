"""Websocket-доставка notification_api (S10_T4, issue #97): подключение с
валидным токеном auth_service получает заявку с channel=websocket, без
токена — отклоняется. По образцу tests/notification_api/conftest.py."""

import os
import uuid

import aiohttp
import pytest
import pytest_asyncio

from .conftest import BASE_URL, make_request, post_notification


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


AUTH_API_HOST = os.getenv(
    'AUTH_API_HOST', 'auth_service' if is_docker() else '127.0.0.1'
)
AUTH_API_PORT = int(os.getenv('AUTH_API_PORT', '8000' if is_docker() else '8001'))
AUTH_BASE_URL = f"http://{AUTH_API_HOST}:{AUTH_API_PORT}/api/v1/auth"

WS_URL = f"{BASE_URL}/ws"

PASSWORD = "WsSmokePass123!"


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


@pytest_asyncio.fixture(name='ws_user')
async def ws_user(session):
    """Регистрирует и логинит нового пользователя auth_service, возвращает
    его id и access_token."""
    email = f"ws_smoke_{uuid.uuid4().hex[:12]}@example.com"
    async with session.post(
        f"{AUTH_BASE_URL}/register",
        json={"email": email, "password": PASSWORD, "full_name": "WS Smoke"},
    ) as response:
        assert response.status == 201, await response.text()
        user_id = (await response.json())["id"]

    async with session.post(
        f"{AUTH_BASE_URL}/login", json={"email": email, "password": PASSWORD}
    ) as response:
        assert response.status == 200, await response.text()
        token = (await response.json())["access_token"]

    return {"id": user_id, "token": token}


class TestWebsocketAuth:
    """Сервер отклоняет подключение до accept() (close без него —
    рекомендованный Starlette-способ отвергнуть по auth), поэтому клиент
    видит не успешный коннект с последующим close-фреймом, а провал самого
    HTTP-upgrade — WSServerHandshakeError на ws_connect()."""

    async def test_connect_without_token_rejected(self, session):
        with pytest.raises(aiohttp.WSServerHandshakeError):
            async with session.ws_connect(WS_URL):
                pass

    async def test_connect_with_invalid_token_rejected(self, session):
        with pytest.raises(aiohttp.WSServerHandshakeError):
            async with session.ws_connect(f"{WS_URL}?token=garbage"):
                pass


class TestWebsocketDelivery:
    async def test_text_override_delivered_to_connected_user(self, session, ws_user):
        async with session.ws_connect(
            f"{WS_URL}?token={ws_user['token']}"
        ) as ws:
            request = make_request(
                source_service="smoke-test",
                channel="websocket",
                template_id=None,
                text_override="У вас новое уведомление",
                recipient_ids=[ws_user["id"]],
            )
            status, body = await post_notification(session, request)
            assert status == 202, body
            assert body["status"] == "accepted"

            message = await ws.receive_json(timeout=15)
            assert message["text"] == "У вас новое уведомление"
            assert message["request_id"] == request["request_id"]

    async def test_template_only_rejected(self, session, ws_user):
        """MVP: рендеринг шаблонов не поддержан для websocket — заявка
        только с template_id (без text_override) отклоняется синхронно, в
        самом HTTP-ответе (см. §10 контракта), а не молча теряется."""
        request = make_request(
            source_service="smoke-test",
            channel="websocket",
            recipient_ids=[ws_user["id"]],
        )
        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "rejected"
        assert body["rejected_recipients"] == [
            {"user_id": ws_user["id"], "reason": "websocket_requires_text_override"}
        ]

    async def test_no_active_connection_still_accepted(self, session, ws_user):
        """Best-effort: заявка с text_override получателю без открытого
        соединения всё равно accepted на уровне HTTP — как и у остальных
        каналов, "accepted" не означает "доставлено"."""
        request = make_request(
            source_service="smoke-test",
            channel="websocket",
            template_id=None,
            text_override="никто не слушает",
            recipient_ids=[ws_user["id"]],
        )
        status, body = await post_notification(session, request)
        assert status == 202, body
        assert body["status"] == "accepted"
