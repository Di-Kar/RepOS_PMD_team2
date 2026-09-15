"""Kafka producer: публикация заявок на уведомления (раздел 1 контракта
docs/notification_requests_contract.md) — единственный топик, один consumer
group на всё расширение схемы за счёт поля channel/template_id."""

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
        # Идемпотентный продюсер: ретраи на уровне брокера не создают дублей
        # при сетевых сбоях, требует acks="all".
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


async def publish_notification(key: str, value: dict) -> None:
    """Публикует одно сообщение (уже после фан-аута — один получатель) и
    ждёт подтверждения от брокера (send_and_wait): вызывающий код узнаёт об
    успехе только после реального ack."""
    producer = get_producer()
    await producer.send_and_wait(settings.kafka_topic_requests, key=key, value=value)
