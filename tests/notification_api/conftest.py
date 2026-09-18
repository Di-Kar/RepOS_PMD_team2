"""Фикстуры HTTP+Kafka смоук-тестов notification_api (black-box): отправляем
заявки через HTTP API и вычитываем результат фан-аута обратно из Kafka, чтобы
подтвердить доставку — по образцу tests/event_api/conftest.py."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import aiohttp
import asyncpg
import pytest_asyncio
from aiokafka import AIOKafkaConsumer


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


NOTIFICATION_API_HOST = os.getenv(
    'NOTIFICATION_API_HOST', 'notification_api' if is_docker() else '127.0.0.1'
)
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8004.
NOTIFICATION_API_PORT = int(
    os.getenv('NOTIFICATION_API_PORT', '8000' if is_docker() else '8004')
)
BASE_URL = (
    f"http://{NOTIFICATION_API_HOST}:{NOTIFICATION_API_PORT}/api/v1/notifications"
)

# Kafka не проброшен на хост (как auth_redis/async_api_redis) — тесты
# рассчитаны на запуск через docker-compose --profile tests.
KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'NOTIFICATIONS_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'
)
TOPIC_REQUESTS = os.getenv(
    'NOTIFICATIONS_KAFKA_TOPIC_REQUESTS', 'notifications.requests.v1'
)

API_KEY = os.getenv('NOTIFICATIONS_API_KEY', '')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Postgres notification_api (лог заявок, docs/notification_requests_contract.md
# §9) не проброшен на хост для тестов — как и Kafka, рассчитан на запуск через
# docker-compose --profile tests.
NOTIFICATIONS_POSTGRES_HOST = os.getenv(
    'NOTIFICATIONS_POSTGRES_HOST', 'notification_postgres'
)
NOTIFICATIONS_POSTGRES_PORT = int(os.getenv('NOTIFICATIONS_POSTGRES_PORT', '5432'))
# Без "S" — так реально называется в .env/.env.example и docker-compose.yml
# (POSTGRES_USER/PASSWORD/DB сервиса notification_postgres); с "S" в env_file
# такой переменной нет, и подключение падает на дефолтных кредах.
NOTIFICATIONS_POSTGRES_USER = os.getenv('NOTIFICATION_POSTGRES_USER', 'notify_user')
NOTIFICATIONS_POSTGRES_PASSWORD = os.getenv(
    'NOTIFICATION_POSTGRES_PASSWORD', 'notify_secret'
)
NOTIFICATIONS_POSTGRES_DB = os.getenv('NOTIFICATION_POSTGRES_DB', 'notifications_db')


def make_request(**overrides) -> dict:
    """Собирает валидную заявку по контракту
    docs/notification_requests_contract.md §3; overrides позволяет тестам
    ломать/переопределять отдельные поля."""
    request = {
        "request_id": str(uuid.uuid4()),
        "source_service": "smoke-test",
        "channel": "email",
        "template_id": "1",
        "context": {},
        "recipient_ids": [str(uuid.uuid4())],
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    request.update(overrides)
    return request


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


async def post_notification(session: aiohttp.ClientSession, body: dict) -> tuple:
    async with session.post(BASE_URL, json=body, headers=HEADERS) as response:
        return response.status, await response.json()


async def post_batch(session: aiohttp.ClientSession, requests: list) -> tuple:
    async with session.post(
        f"{BASE_URL}/batch", json={"requests": requests}, headers=HEADERS
    ) as response:
        return response.status, await response.json()


class KafkaWatcher:
    """Слушает топик с самого начала (уникальная consumer group на инстанс),
    поэтому не важно, успел ли consumer подписаться до публикации сообщения."""

    def __init__(self, consumer: AIOKafkaConsumer):
        self._consumer = consumer

    async def wait_for(self, predicate, timeout: float = 15.0) -> dict | None:
        """predicate(record, value) -> bool; True — искомое сообщение найдено,
        остановить ожидание и вернуть его value."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            remaining_ms = max(int((deadline - loop.time()) * 1000), 100)
            batches = await self._consumer.getmany(timeout_ms=min(remaining_ms, 2000))
            for records in batches.values():
                for record in records:
                    value = json.loads(record.value)
                    if predicate(record, value):
                        return value
        return None


@pytest_asyncio.fixture(name='kafka_watcher')
async def kafka_watcher():
    """Фабрика консьюмеров: `watcher = await kafka_watcher(TOPIC_REQUESTS)`."""
    consumers: list[AIOKafkaConsumer] = []

    async def _make(topic: str) -> KafkaWatcher:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"notification_api_smoke_{uuid.uuid4().hex}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await consumer.start()
        consumers.append(consumer)
        return KafkaWatcher(consumer)

    yield _make

    for consumer in consumers:
        await consumer.stop()


@pytest_asyncio.fixture(name='db_conn')
async def db_conn():
    """Прямое подключение к БД notification_api — читаем notification_log
    (§9), чтобы проверить, что заявка зафиксирована с ожидаемым статусом."""
    conn = await asyncpg.connect(
        host=NOTIFICATIONS_POSTGRES_HOST,
        port=NOTIFICATIONS_POSTGRES_PORT,
        user=NOTIFICATIONS_POSTGRES_USER,
        password=NOTIFICATIONS_POSTGRES_PASSWORD,
        database=NOTIFICATIONS_POSTGRES_DB,
    )
    yield conn
    await conn.close()
