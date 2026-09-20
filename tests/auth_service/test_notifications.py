"""auth_service -> notification_api (S10_T7, issue #100): регистрация и смена
пароля публикуют заявку в notifications.requests.v1 (по контракту
docs/notification_requests_contract.md). По образцу
tests/notification_api/conftest.py (KafkaWatcher)."""

import asyncio
import json
import os
import uuid

import pytest_asyncio
from aiokafka import AIOKafkaConsumer

from .conftest import BASE_URL, PASSWORD, bearer, post_json

NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'
)
NOTIFICATIONS_TOPIC_REQUESTS = os.getenv(
    'NOTIFICATIONS_KAFKA_TOPIC_REQUESTS', 'notifications.requests.v1'
)


async def _wait_for_notification(consumer, predicate, timeout: float = 15.0) -> dict | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        remaining_ms = max(int((deadline - loop.time()) * 1000), 100)
        batches = await consumer.getmany(timeout_ms=min(remaining_ms, 2000))
        for records in batches.values():
            for record in records:
                value = json.loads(record.value)
                if predicate(value):
                    return value
    return None


@pytest_asyncio.fixture(name='notifications_consumer')
async def notifications_consumer():
    """Слушает notifications.requests.v1 с самого начала — уникальная
    consumer group на тест, поэтому неважно, кто подписался раньше."""
    consumer = AIOKafkaConsumer(
        NOTIFICATIONS_TOPIC_REQUESTS,
        bootstrap_servers=NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS,
        group_id=f'auth_service_smoke_{uuid.uuid4().hex}',
        auto_offset_reset='earliest',
        enable_auto_commit=False,
    )
    await consumer.start()
    yield consumer
    await consumer.stop()


class TestNotifications:
    async def test_register_sends_welcome_notification(
        self, session, notifications_consumer
    ):
        email = f"smoke_notify_{uuid.uuid4().hex[:12]}@example.com"
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/register",
            {"email": email, "password": PASSWORD, "full_name": "Notify Me"},
        )
        assert status == 201, body
        user_id = body["id"]

        message = await _wait_for_notification(
            notifications_consumer,
            lambda value: value["source_service"] == "auth_service"
            and value["user_id"] == user_id,
        )
        assert message is not None, "заявка на приветственное письмо не дошла до Kafka"
        assert message["channel"] == "email"
        assert message["text_override"]
        # welcome-письмо должно нести сокращённую ссылку подтверждения email
        # (docs/link_shortener_contract.md).
        # Это отдельный сервис (link_shortener_service) — если он недоступен,
        # auth_service best-effort деградирует до письма без ссылки (см.
        # src/services/registration_notifications.py), поэтому здесь мы
        # именно требуем её наличие: в тестовом окружении link_shortener_service
        # обязателен (docker-compose.yml, зависимость сервиса tests).
        assert "/r/" in message["text_override"], (
            "welcome-письмо не содержит короткую ссылку подтверждения email"
        )

    async def test_change_password_sends_notification(
        self, session, new_user, login, notifications_consumer
    ):
        tokens = await login(new_user)
        status, body = await post_json(
            session,
            f"{BASE_URL}/auth/change-password",
            {"current_password": PASSWORD, "new_password": "NewNotifyPass456!"},
            headers=bearer(tokens),
        )
        assert status == 200, body

        # У new_user уже была своя заявка на приветственное письмо (та же
        # user_id) — отличаем заявку о смене пароля по subject_override.
        message = await _wait_for_notification(
            notifications_consumer,
            lambda value: value["source_service"] == "auth_service"
            and value["user_id"] == new_user["id"]
            and value["subject_override"] == "Пароль изменён",
        )
        assert message is not None, "заявка об изменении пароля не дошла до Kafka"
