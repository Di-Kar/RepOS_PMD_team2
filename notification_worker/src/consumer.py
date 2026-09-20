"""Общий Kafka consumer-loop, переиспользуемый обеими стадиями (render и
email_sender) — manual commit после успешной обработки, ретраи с backoff на
транзиентных ошибках, пауза только застрявшей партиции при исчерпании
ретраев (остальные партиции — другие пользователи — продолжают
обрабатываться этим же процессом), commit-and-skip на постоянных ошибках,
и предел числа циклов паузы — после него сообщение фиксируется в DLQ как
необработанное, а не крутится pause/resume бесконечно (см. ревью: без
предела один "плохой" месседж мог заблокировать партицию навсегда).

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
import uuid
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition

from src.core.config import settings
from src.core.errors import PermanentProcessingError
from src.core.message_utils import safe_raw_message
from src.db import queries
from src.db.postgres import get_pool

logger = logging.getLogger(__name__)

# attempt_id — стабилен на протяжении всех попыток (включая паузы/резюме)
# обработки ОДНОГО сообщения этим процессом, меняется на новый случайный
# только когда consumer.py заново получает это сообщение "с нуля" (после
# перезапуска процесса или переигровки offset'а) — используется send-стадией
# (src/services/send_service.py), чтобы отличить "я сам продолжаю ретраить"
# от "предыдущий вызов упал, не закончив" без угадывания по времени.
Handler = Callable[[ConsumerRecord, uuid.UUID], Awaitable[None]]


async def run_consumer_loop(
    *, topic: str, group_id: str, handler: Handler, stage: str
) -> None:
    """Запускает consumer-loop и блокируется, пока его не остановят
    (KeyboardInterrupt/SIGTERM снаружи — main_*.py ловит их для graceful
    shutdown). `stage` ("render"/"send") — только для записи в DLQ, когда
    сообщение исчерпало все циклы паузы (см. _process_with_retry)."""
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
            asyncio.create_task(_consume_partition(consumer, tp, handler, stage))
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
    consumer: AIOKafkaConsumer, tp: TopicPartition, handler: Handler, stage: str
) -> None:
    """Независимый цикл на одну партицию — getmany ограничен этой
    партицией, поэтому pause/sleep на ней не блокирует getmany других
    партиций, выполняющихся в своих задачах параллельно (кооперативно, через
    asyncio)."""
    while True:
        batches = await consumer.getmany(tp, timeout_ms=1000)
        records = batches.get(tp, [])
        for record in records:
            # Новый attempt_id на каждое СВЕЖЕЕ (из getmany) сообщение —
            # внутри _process_with_retry он остаётся одним и тем же на
            # протяжении всех попыток/пауз этого конкретного вызова.
            await _process_with_retry(consumer, tp, record, handler, stage, uuid.uuid4())


async def _give_up(
    tp: TopicPartition, record: ConsumerRecord, stage: str, exc: Exception
) -> None:
    """Сообщение исчерпало max_pause_cycles попыток — фиксируем в DLQ как
    необработанное и отпускаем партицию, вместо того чтобы крутить
    pause/resume бесконечно (см. докстринг модуля)."""
    logger.error(
        f"Giving up on message after {settings.max_pause_cycles} pause cycles "
        f"(topic={record.topic} partition={record.partition} offset={record.offset}): {exc}"
    )
    try:
        await queries.insert_dlq(
            get_pool(),
            notification_id=None,
            stage=stage,
            error_type="giving_up_after_max_pause_cycles",
            error_message=str(exc),
            raw_message=safe_raw_message(record.value),
            attempt_count=settings.max_pause_cycles,
        )
    except Exception as dlq_exc:  # noqa: BLE001 — не даём сбою записи в DLQ снова застрять на этом же сообщении
        logger.error(f"Failed to write give-up DLQ entry: {dlq_exc}")


async def _process_with_retry(
    consumer: AIOKafkaConsumer,
    tp: TopicPartition,
    record: ConsumerRecord,
    handler: Handler,
    stage: str,
    attempt_id: uuid.UUID,
) -> None:
    attempt = 0
    pause_cycles = 0
    while True:
        attempt += 1
        try:
            await handler(record, attempt_id)
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
            if attempt <= settings.retry_max_attempts:
                backoff = settings.retry_backoff_seconds * attempt
                logger.warning(
                    f"Transient error (attempt {attempt}/{settings.retry_max_attempts}, "
                    f"partition={record.partition} offset={record.offset}), "
                    f"retrying in {backoff}s: {exc}"
                )
                await asyncio.sleep(backoff)
                continue

            pause_cycles += 1
            if pause_cycles > settings.max_pause_cycles:
                await _give_up(tp, record, stage, exc)
                await consumer.commit({tp: record.offset + 1})
                return

            logger.error(
                f"Exhausted retries for partition {record.partition} "
                f"(offset={record.offset}), pausing for "
                f"{settings.partition_pause_seconds}s before retrying again "
                f"(pause cycle {pause_cycles}/{settings.max_pause_cycles}): {exc}"
            )
            consumer.pause(tp)
            await asyncio.sleep(settings.partition_pause_seconds)
            consumer.resume(tp)
            attempt = 0
            continue
