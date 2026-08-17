"""Smoke-тесты analytics_etl: Kafka → ETL → ClickHouse.

Сценарий:
  1. Публикуем события через aiokafka.Producer в Kafka-топики.
  2. Ждём, пока analytics_etl сконсумит, трансформирует и запишет в ClickHouse.
  3. Вычитываем данные из ClickHouse через clickhouse_connect.
  4. Assert — данные существуют и корректны.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import Client
import pytest_asyncio
from aiokafka import AIOKafkaProducer

# --- Config from env ---

ANALYTICS_KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'ANALYTICS_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'
)
ANALYTICS_CLICKHOUSE_HOST = os.getenv('ANALYTICS_CLICKHOUSE_HOST', 'clickhouse')
ANALYTICS_CLICKHOUSE_HTTP_PORT = int(os.getenv('ANALYTICS_CLICKHOUSE_HTTP_PORT', '8123'))
ANALYTICS_CLICKHOUSE_USER = os.getenv('ANALYTICS_CLICKHOUSE_USER', 'default')
ANALYTICS_CLICKHOUSE_PASSWORD = os.getenv('ANALYTICS_CLICKHOUSE_PASSWORD', 'secret')
ANALYTICS_CLICKHOUSE_DATABASE = os.getenv('ANALYTICS_CLICKHOUSE_DATABASE', 'analytics')

TOPIC_CLICKS = 'analytics.clicks.v1'
TOPIC_CUSTOM_EVENTS = 'analytics.custom_events.v1'


def make_click_event(event_id: str | None = None) -> dict:
    """Собирает валидное click event по контракту."""
    return {
        'event_id': event_id or str(uuid.uuid4()),
        'event_type': 'click',
        'schema_version': 1,
        'occurred_at': datetime.now(timezone.utc).isoformat(),
        'received_at': datetime.now(timezone.utc).isoformat(),
        'user_id': f'smoke-user-{uuid.uuid4().hex[:8]}',
        'session_id': str(uuid.uuid4()),
        'sequence_number': 1,
        'consent': True,
        'context': {
            'page_type': 'movie_card',
            'page_id': 'tt0111161',
            'device': 'desktop',
            'app_version': '3.4.1',
        },
        'source': 'web',
        'payload': {
            'element_id': 'play-button',
            'element_type': 'button',
            'zone': 'hero',
            'attrs': {'content_id': 'tt0111161'},
        },
    }


def make_quality_change_event(
    event_id: str | None = None,
    content_id: str = 'tt0111161',
    watch_session_id: str | None = None,
) -> dict:
    """Собирает валидное quality_change custom_event."""
    return {
        'event_id': event_id or str(uuid.uuid4()),
        'event_type': 'custom_event',
        'schema_version': 1,
        'occurred_at': datetime.now(timezone.utc).isoformat(),
        'received_at': datetime.now(timezone.utc).isoformat(),
        'user_id': f'smoke-user-{uuid.uuid4().hex[:8]}',
        'session_id': str(uuid.uuid4()),
        'sequence_number': 27,
        'consent': True,
        'context': {
            'page_type': 'watch',
            'page_id': content_id,
        },
        'source': 'web',
        'payload': {
            'custom_event_type': 'quality_change',
            'content_id': content_id,
            'watch_session_id': watch_session_id or f'ws-{uuid.uuid4().hex[:8]}',
            'from_quality': '720p',
            'to_quality': '1080p',
        },
    }


# --- Fixtures ---


@pytest_asyncio.fixture(name='clickhouse_client')
async def clickhouse_client_fixture():
    """clickhouse_connect client (HTTP protocol, port 8123)."""
    client = await clickhouse_connect.get_async_client(
        host=ANALYTICS_CLICKHOUSE_HOST,
        port=ANALYTICS_CLICKHOUSE_HTTP_PORT,
        database=ANALYTICS_CLICKHOUSE_DATABASE,
        username=ANALYTICS_CLICKHOUSE_USER,
        password=ANALYTICS_CLICKHOUSE_PASSWORD,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture(name='kafka_producer')
async def kafka_producer_fixture():
    """aiokafka Producer для публикации событий в smoke-тестах."""
    producer = AIOKafkaProducer(
        bootstrap_servers=ANALYTICS_KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    )
    await producer.start()
    yield producer
    await producer.stop()


# --- Helpers ---


async def wait_for_data(
    client: Client,
    query: str,
    timeout: float = 15,
    poll_interval: float = 2,
    data_checker: callable = None,
) -> list:
    """Poll ClickHouse until query returns data or timeout is reached.
    
    Args:
        data_checker: callback(rows) -> bool. If None, checks len(rows) > 0.
    """
    if data_checker is None:
        data_checker = lambda rows: len(rows) > 0
    
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            result = await client.query(query)
            rows = result.result_rows
            if data_checker(rows):
                return rows
        except Exception:
            pass
        await asyncio.sleep(poll_interval)
    raise AssertionError(f"Data not found after {timeout}s")


# --- Tests ---


async def test_events_table_populated(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: Client,
):
    """Тест 1: publish click → ETL → ClickHouse.events содержит запись."""
    event_id = f'click-test-{uuid.uuid4().hex[:8]}'
    event = make_click_event(event_id)

    # Публикуем событие
    await kafka_producer.send(
        TOPIC_CLICKS,
        value=event,
    )
    await kafka_producer.flush()

    # Ждём, пока ETL запишет в ClickHouse и проверим count
    query = f"SELECT count() FROM events WHERE event_type = 'click' AND event_id = '{event_id}'"
    rows = await wait_for_data(
        clickhouse_client, query, data_checker=lambda rows: rows[0][0] > 0
    )

    assert rows[0][0] >= 1, f'Expected at least 1 click event in ClickHouse'


async def test_movies_metrics_aggregated(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: Client,
):
    """Тест 2: publish quality_change → ETL → ClickHouse.movies_metrics обновлён."""
    content_id = f'content-{uuid.uuid4().hex[:6]}'
    event = make_quality_change_event(content_id=content_id)

    await kafka_producer.send(TOPIC_CUSTOM_EVENTS, value=event)
    await kafka_producer.flush()

    # Ждём агрегации movies_metrics
    query = f"SELECT content_id, total_views FROM movies_metrics WHERE content_id = '{content_id}'"
    rows = await wait_for_data(
        clickhouse_client,
        query,
        timeout=15,
        data_checker=lambda rows: len(rows) >= 1,
    )

    assert len(rows) >= 1, f'Expected movies_metrics row for content_id={content_id}'
    assert rows[0][1] >= 1, f'total_views should be >= 1, got {rows[0][1]}'


async def test_watch_sessions_recorded(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: Client,
):
    """Тест 3: publish quality_change с watch_session_id → ETL → ClickHouse.watch_sessions."""
    content_id = f'content-{uuid.uuid4().hex[:6]}'
    watch_session_id = f'ws-test-{uuid.uuid4().hex[:8]}'
    event = make_quality_change_event(
        content_id=content_id,
        watch_session_id=watch_session_id,
    )

    await kafka_producer.send(TOPIC_CUSTOM_EVENTS, value=event)
    await kafka_producer.flush()

    # Ждём записи watch_sessions
    query = f"SELECT watch_session_id FROM watch_sessions WHERE watch_session_id = '{watch_session_id}'"
    rows = await wait_for_data(
        clickhouse_client,
        query,
        timeout=15,
        data_checker=lambda rows: len(rows) >= 1,
    )

    assert len(rows) >= 1, (
        f'Expected watch_session row for watch_session_id={watch_session_id}'
    )


async def test_multiple_events_batch(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: Client,
):
    """Тест 4: publish 5 click events → ETL → ClickHouse.events содержит >= 5 записей."""
    event_ids = [f'batch-click-{uuid.uuid4().hex[:8]}' for _ in range(5)]

    # Публикуем батч
    for eid in event_ids:
        event = make_click_event(eid)
        await kafka_producer.send(TOPIC_CLICKS, value=event)
    await kafka_producer.flush()

    # Ждём все 5 записей
    placeholders = ','.join(["'{0}'".format(eid) for eid in event_ids])
    query = f"SELECT event_id FROM events WHERE event_id IN ({placeholders})"

    # Poll until we have 5 rows
    deadline = asyncio.get_event_loop().time() + 15
    last_error = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            result = await clickhouse_client.query(query)
            if len(result.result_rows) >= 5:
                break
        except Exception as exc:
            last_error = exc
        await asyncio.sleep(2)
    else:
        raise AssertionError(
            f'Expected at least 5 rows in events table. Last error: {last_error}'
        )
