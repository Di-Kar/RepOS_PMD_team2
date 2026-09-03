"""Kafka producer: публикация событий, роутинг по топикам (раздел 1 контракта)."""

import json
import logging
from typing import Optional

from aiokafka import AIOKafkaProducer

from src.core.config import settings

logger = logging.getLogger(__name__)

_producer: Optional[AIOKafkaProducer] = None

_TOPIC_BY_KEY = {
    "clicks": lambda: settings.kafka_topic_clicks,
    "pageviews": lambda: settings.kafka_topic_pageviews,
    "custom_events": lambda: settings.kafka_topic_custom_events,
}


def resolve_topic(topic_key: str) -> str:
    return _TOPIC_BY_KEY[topic_key]()


async def init_producer() -> None:
    global _producer
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks=settings.kafka_acks,
        # Идемпотентный продюсер: ретраи на уровне брокера не создают дублей
        # при сетевых сбоях (NFR-9), требует acks="all".
        enable_idempotence=True,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8"),
        linger_ms=10,
        retry_backoff_ms=200,
    )
    await _producer.start()
    logger.info(f"Kafka producer started: {settings.kafka_bootstrap_servers}")


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("Kafka producer stopped.")


def get_producer() -> AIOKafkaProducer:
    if _producer is None:
        raise RuntimeError("Kafka producer is not initialized")
    return _producer


async def publish_event(topic_key: str, key: str, value: dict) -> None:
    """Публикует событие и ждёт подтверждения от брокера (send_and_wait) —
    клиент должен узнавать об успехе только после реального ack (NFR-7).
    Исключение пробрасывается вызывающему коду: клиент по FR-29 обязан уметь
    повторно отправить событие, если публикация не удалась."""
    producer = get_producer()
    topic = resolve_topic(topic_key)
    await producer.send_and_wait(topic, key=key, value=value)
