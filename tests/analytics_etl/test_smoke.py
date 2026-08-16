"""Smoke-тесты analytics_etl: Kafka → ETL → ClickHouse.

Сценарий:
  1. Публикуем события через aiokafka.Producer в Kafka-топики.
  2. Ждём, пока analytics_etl сконсумит, трансформирует и запишет в ClickHouse.
  3. Вычитываем данные из ClickHouse через clickhouse_connect (native, port=9000).
  4. Assert — данные существуют и корректны.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import clickhouse_connect
import pytest_asyncio
from aiokafka import AIOKafkaProducer

# --- Config from env ---

ANALYTICS_KAFKA_BOOTSTRAP_SERVERS = os.getenv(
    'ANALYTICS_KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'
)
ANALYTICS_CLICKHOUSE_HOST = os.getenv('ANALYTICS_CLICKHOUSE_HOST', 'clickhouse')
ANALYTICS_CLICKHOUSE_PORT = int(os.getenv('ANALYTICS_CLICKHOUSE_PORT', '9000'))
ANALYTICS_CLICKHOUSE_DATABASE = os.getenv('ANALYTICS_CLICKHOUSE_DATABASE', 'analytics')

TOPIC_CLICKS = 'analytics.clicks.v1'
TOPIC_CUSTOM_EVENTS = 'analytics.custom_events.v1'

# Таймаут ожидания: ETL flush interval = 5s, двойной запас + overhead.
WAIT_TIMEOUT = 30


def _is_docker() -> bool:
    return os.path.exists('/.dockerenv')


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
def clickhouse_client_fixture():
    """clickhouse_connect client (native protocol, port 9000)."""
    client = clickhouse_connect.get_client(
        host=ANALYTICS_CLICKHOUSE_HOST,
        port=ANALYTICS_CLICKHOUSE_PORT,
        database=ANALYTICS_CLICKHOUSE_DATABASE,
    )
    yield client
    client.close()


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


def wait_for_data(
    client: clickhouse_connect.Client,
    query: str,
    params: dict | None = None,
    timeout: float = WAIT_TIMEOUT,
) -> list:
    """Полл-хелпер: повторяем запрос каждые 2s до timeout или пока данные не появятся."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            result = client.query(query, params)
            rows = result.result_rows
            if rows:
                return rows
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise AssertionError(
        f'Data not found in ClickHouse after {timeout}s. Last error: {last_error}'
    )


# --- Tests ---


def test_events_table_populated(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: clickhouse_connect.Client,
):
    """Тест 1: publish click → ETL → ClickHouse.events содержит запись."""
    event_id = f'click-test-{uuid.uuid4().hex[:8]}'
    event = make_click_event(event_id)

    # Публикуем событие
    future = kafka_producer.send(
        TOPIC_CLICKS,
        value=event,
    )
    future.get(timeout=10)  # дожидаемся успешной отправки

    # Ждём, пока ETL запишет в ClickHouse
    rows = wait_for_data(
        clickhouse_client,
        'SELECT event_id FROM analytics.events WHERE event_id = %s',
        {'param1': event_id},
    )

    assert len(rows) >= 1, f'Expected at least 1 row for event_id={event_id}'


def test_movies_metrics_aggregated(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: clickhouse_connect.Client,
):
    """Тест 2: publish quality_change → ETL → ClickHouse.movies_metrics обновлён."""
    content_id = f'content-{uuid.uuid4().hex[:6]}'
    event = make_quality_change_event(
        content_id=content_id,
    )

    future = kafka_producer.send(TOPIC_CUSTOM_EVENTS, value=event)
    future.get(timeout=10)

    # Ждём агрегации movies_metrics
    rows = wait_for_data(
        clickhouse_client,
        'SELECT content_id, total_views FROM analytics.movies_metrics WHERE content_id = %s',
        {'param1': content_id},
    )

    assert len(rows) >= 1, f'Expected movies_metrics row for content_id={content_id}'
    assert rows[0][1] >= 1, f'total_views should be >= 1, got {rows[0][1]}'


def test_watch_sessions_recorded(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: clickhouse_connect.Client,
):
    """Тест 3: publish quality_change с watch_session_id → ETL → ClickHouse.watch_sessions."""
    content_id = f'content-{uuid.uuid4().hex[:6]}'
    watch_session_id = f'ws-test-{uuid.uuid4().hex[:8]}'
    event = make_quality_change_event(
        content_id=content_id,
        watch_session_id=watch_session_id,
    )

    future = kafka_producer.send(TOPIC_CUSTOM_EVENTS, value=event)
    future.get(timeout=10)

    # Ждём записи watch_sessions
    rows = wait_for_data(
        clickhouse_client,
        'SELECT watch_session_id FROM analytics.watch_sessions WHERE watch_session_id = %s',
        {'param1': watch_session_id},
    )

    assert len(rows) >= 1, (
        f'Expected watch_session row for watch_session_id={watch_session_id}'
    )


def test_multiple_events_batch(
    kafka_producer: AIOKafkaProducer,
    clickhouse_client: clickhouse_connect.Client,
):
    """Тест 4: publish 5 click events → ETL → ClickHouse.events содержит >= 5 записей."""
    event_ids = [f'batch-click-{uuid.uuid4().hex[:8]}' for _ in range(5)]

    # Публикуем батч
    futures = []
    for eid in event_ids:
        event = make_click_event(eid)
        futures.append(kafka_producer.send(TOPIC_CLICKS, value=event))
    for fut in futures:
        fut.get(timeout=10)

    # Ждём все 5 записей
    placeholders = ','.join(['%s'] * len(event_ids))
    rows = wait_for_data(
        clickhouse_client,
        f'SELECT event_id FROM analytics.events WHERE event_id IN ({placeholders})',
        {f'param{i + 1}': eid for i, eid in enumerate(event_ids)},
    )

    assert len(rows) >= 5, f'Expected at least 5 rows, got {len(rows)}'
