"""Общий Kafka consumer-loop, переиспользуемый обеими стадиями (render и
email_sender) — manual commit после успешной обработки, ретраи с backoff на
транзиентных ошибках, пауза только застрявшей партиции при исчерпании
ретраев (остальные партиции — другие пользователи — продолжают
обрабатываться этим же процессом), commit-and-skip на постоянных ошибках.

Каждая назначенная консьюмеру партиция обрабатывается своей asyncio-задачей
(свой независимый цикл `getmany` на эту партицию) — это и даёт "пауза одной
партиции не блокирует остальные" внутри одного процесса, а не только между
репликами. Упрощение: список партиций фиксируется сразу после
`consumer.start()` и не пересчитывается при последующих ребалансах (смена
числа реплик группы на лету) — для фиксированных 3 партиций топика в этом
проекте (см. kafka_init) этого достаточно; полноценная поддержка
динамического ребаланса (ConsumerRebalanceListener пересоздаёт задачи)
осталась бы доработкой, если понадобится масштабирование сверх 3 реплик."""

import asyncio
import logging
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition

from src.core.config import settings
from src.core.errors import PermanentProcessingError, TransientProcessingError

logger = logging.getLogger(__name__)

Handler = Callable[[ConsumerRecord], Awaitable[None]]


async def run_consumer_loop(*, topic: str, group_id: str, handler: Handler) -> None:
    """Запускает consumer-loop и блокируется, пока его не остановят
    (KeyboardInterrupt/SIGTERM снаружи — main_*.py ловит их для graceful
    shutdown)."""
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info(f"Kafka consumer started: topic={topic} group_id={group_id}")
    try:
        partitions = await _wait_for_assignment(consumer)
        logger.info(f"Assigned partitions: {sorted(tp.partition for tp in partitions)}")
        tasks = [
            asyncio.create_task(_consume_partition(consumer, tp, handler))
            for tp in partitions
        ]
        await asyncio.gather(*tasks)
    finally:
        await consumer.stop()
        logger.info(f"Kafka consumer stopped: topic={topic} group_id={group_id}")


async def _wait_for_assignment(
    consumer: AIOKafkaConsumer, timeout: float = 30.0
) -> list[TopicPartition]:
    """aiokafka присваивает партиции как часть group-join внутри
    `consumer.start()`, но на всякий случай (не все версии/сценарии это
    гарантируют синхронно) дожидаемся непустого assignment явно, не читая
    сообщения вслепую (это могло бы потерять их из вида до старта задач)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        assignment = consumer.assignment()
        if assignment:
            return sorted(assignment, key=lambda tp: tp.partition)
        if loop.time() > deadline:
            raise RuntimeError("Timed out waiting for Kafka partition assignment")
        await asyncio.sleep(0.5)


async def _consume_partition(
    consumer: AIOKafkaConsumer, tp: TopicPartition, handler: Handler
) -> None:
    """Независимый цикл на одну партицию — getmany ограничен этой
    партицией, поэтому pause/sleep на ней не блокирует getmany других
    партиций, выполняющихся в своих задачах параллельно (кооперативно, через
    asyncio)."""
    while True:
        batches = await consumer.getmany(tp, timeout_ms=1000)
        records = batches.get(tp, [])
        for record in records:
            await _process_with_retry(consumer, tp, record, handler)


async def _process_with_retry(
    consumer: AIOKafkaConsumer,
    tp: TopicPartition,
    record: ConsumerRecord,
    handler: Handler,
) -> None:
    attempt = 0
    while True:
        attempt += 1
        try:
            await handler(record)
            await consumer.commit({tp: record.offset + 1})
            return
        except PermanentProcessingError as exc:
            # Обработчик уже должен был зафиксировать причину (DLQ/
            # notification_log) до того, как поднять это исключение —
            # здесь только пропускаем сообщение, партиция не блокируется.
            logger.error(
                f"Permanent error, skipping message (topic={record.topic} "
                f"partition={record.partition} offset={record.offset}): {exc}"
            )
            await consumer.commit({tp: record.offset + 1})
            return
        except Exception as exc:  # noqa: BLE001 — любая иная ошибка тоже транзиентна по умолчанию
            is_declared_transient = isinstance(exc, TransientProcessingError)
            if attempt <= settings.retry_max_attempts:
                backoff = settings.retry_backoff_seconds * attempt
                logger.warning(
                    f"{'Transient' if is_declared_transient else 'Unexpected'} error "
                    f"(attempt {attempt}/{settings.retry_max_attempts}, "
                    f"partition={record.partition} offset={record.offset}), "
                    f"retrying in {backoff}s: {exc}"
                )
                await asyncio.sleep(backoff)
                continue
            logger.error(
                f"Exhausted retries for partition {record.partition} "
                f"(offset={record.offset}), pausing for "
                f"{settings.partition_pause_seconds}s before retrying again: {exc}"
            )
            consumer.pause(tp)
            await asyncio.sleep(settings.partition_pause_seconds)
            consumer.resume(tp)
            attempt = 0
            continue
