"""Фикстуры HTTP+Kafka смоук-тестов event_api (black-box): отправляем события
через HTTP API и вычитываем их обратно из Kafka, чтобы подтвердить доставку."""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import aiohttp
import pytest_asyncio
from aiokafka import AIOKafkaConsumer


def is_docker() -> bool:
    return os.path.exists('/.dockerenv')


EVENT_API_HOST = os.getenv('EVENT_API_HOST', 'event_api' if is_docker() else '127.0.0.1')
# Внутри docker-сети сервис слушает 8000, наружу проброшен как 8002.
EVENT_API_PORT = int(os.getenv('EVENT_API_PORT', '8000' if is_docker() else '8002'))
BASE_URL = f"http://{EVENT_API_HOST}:{EVENT_API_PORT}/api/v1/events"

# Kafka не проброшен на хост (как auth_redis/async_api_redis) — тесты
# рассчитаны на запуск через docker-compose --profile tests.
KAFKA_BOOTSTRAP_SERVERS = os.getenv('EVENTS_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')

TOPIC_CLICKS = os.getenv('EVENTS_KAFKA_TOPIC_CLICKS', 'analytics.clicks.v1')
TOPIC_PAGEVIEWS = os.getenv('EVENTS_KAFKA_TOPIC_PAGEVIEWS', 'analytics.pageviews.v1')
TOPIC_CUSTOM_EVENTS = os.getenv('EVENTS_KAFKA_TOPIC_CUSTOM_EVENTS', 'analytics.custom_events.v1')

API_KEY = os.getenv('EVENTS_API_KEY', '')
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


def make_event(event_type: str, payload: dict, **overrides) -> dict:
    """Собирает валидное событие по контракту docs/user_events_contract.md;
    overrides позволяет тестам ломать/переопределять отдельные поля."""
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "user_id": f"smoke-user-{uuid.uuid4().hex[:8]}",
        "session_id": str(uuid.uuid4()),
        "sequence_number": 1,
        "consent": True,
        "context": {"device": "desktop", "app_version": "smoke-test"},
        "source": "web",
        "payload": payload,
    }
    event.update(overrides)
    return event


@pytest_asyncio.fixture(name='session')
async def session():
    async with aiohttp.ClientSession() as http_session:
        yield http_session


async def post_event(session: aiohttp.ClientSession, body: dict) -> tuple:
    async with session.post(BASE_URL, json=body, headers=HEADERS) as response:
        return response.status, await response.json()


async def post_batch(session: aiohttp.ClientSession, events: list) -> tuple:
    async with session.post(f"{BASE_URL}/batch", json={"events": events}, headers=HEADERS) as response:
        return response.status, await response.json()


class KafkaWatcher:
    """Слушает топик с самого начала (уникальная consumer group на инстанс),
    поэтому не важно, успел ли consumer подписаться до публикации события."""

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
    """Фабрика консьюмеров: `watcher = await kafka_watcher(TOPIC_CLICKS)`."""
    consumers: list[AIOKafkaConsumer] = []

    async def _make(topic: str) -> KafkaWatcher:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"event_api_smoke_{uuid.uuid4().hex}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await consumer.start()
        consumers.append(consumer)
        return KafkaWatcher(consumer)

    yield _make

    for consumer in consumers:
        await consumer.stop()
