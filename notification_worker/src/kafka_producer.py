"""Kafka producer воркера: публикация отрендеренных уведомлений в
notifications.ready.v1 (используется только render-стадией — main_render.py;
email_sender — терминальная стадия, продюсера не запускает)."""

import json
import logging
from typing import Optional

from aiokafka import AIOKafkaProducer

from src.core.config import settings

logger = logging.getLogger(__name__)

_producer: Optional[AIOKafkaProducer] = None


async def init_producer() -> None:
    global _producer
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks=settings.kafka_acks,
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


async def publish_ready(key: str, value: dict) -> None:
    producer = get_producer()
    await producer.send_and_wait(settings.kafka_topic_ready, key=key, value=value)
