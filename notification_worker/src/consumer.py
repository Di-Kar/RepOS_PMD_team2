"""Общий Kafka consumer-loop, переиспользуемый обеими стадиями (render и
email_sender) — manual commit после успешной обработки, ретраи с backoff на
транзиентных ошибках, пауза только застрявшей партиции при исчерпании
ретраев (остальные партиции — другие пользователи — продолжают
обрабатываться этим же процессом), commit-and-skip на постоянных ошибках,
и предел числа циклов паузы — после него сообщение фиксируется в DLQ как
необработанное, а не крутится pause/resume бесконечно (см. ревью: без
предела один "плохой" месседж мог заблокировать партицию навсегда).

Инвариант: _process_with_retry возвращает управление ТОЛЬКО когда результат
или причина сбоя надёжно сохранены — успешная обработка, PermanentProcessing
Error (обработчик записал причину сам, см. src/core/errors.py) или успешная
запись в DLQ. Если DLQ недоступна, offset не подтверждается, партиция
остаётся на паузе и попытки повторяются; после
dlq_unavailable_max_hold_seconds поднимается DlqUnavailableError и процесс
падает, чтобы перезапуститься с неподтверждённого offset'а (см. ревью:
раньше ошибка записи в DLQ глушилась и сообщение коммитилось — при
длительной недоступности Postgres оно исчезало и из доставки, и из DLQ).

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
from src.core.errors import DlqUnavailableError, PermanentProcessingError
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
        try:
            await asyncio.gather(*tasks)
        finally:
            # Упавшая (DlqUnavailableError) или отменённая при shutdown
            # задача не должна оставить соседние висеть на консьюмере,
            # который сейчас будет остановлен.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
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


async def _give_up(record: ConsumerRecord, stage: str, exc: Exception) -> bool:
    """Сообщение исчерпало max_pause_cycles попыток — пытаемся зафиксировать
    его в DLQ как необработанное, вместо того чтобы крутить pause/resume
    бесконечно (см. докстринг модуля). Возвращает True, только если запись
    в DLQ действительно прошла: подтверждать offset, не сохранив причину
    сбоя, нельзя — сообщение исчезло бы и из доставки, и из DLQ."""
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
    except Exception as dlq_exc:  # noqa: BLE001 — сигнализируем наверх, offset остаётся неподтверждённым
        # CRITICAL, а не ERROR: сообщение сейчас нигде не зафиксировано, и
        # партиция стоит. В Sentry уходит через LoggingIntegration
        # (sentry_sdk.init в main_render.py/main_send_email.py).
        logger.critical(
            f"DLQ unavailable, NOT committing message (topic={record.topic} "
            f"partition={record.partition} offset={record.offset}): "
            f"dlq_error={dlq_exc}; original_error={exc}"
        )
        return False
    return True


def _resume_quietly(consumer: AIOKafkaConsumer, tp: TopicPartition) -> None:
    """resume в finally не должен подменять собой исходное исключение —
    партиция к этому моменту может быть уже не назначена (ребаланс), и
    aiokafka поднял бы IllegalStateError."""
    try:
        consumer.resume(tp)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to resume partition {tp.partition}: {exc}")


async def _process_with_retry(
    consumer: AIOKafkaConsumer,
    tp: TopicPartition,
    record: ConsumerRecord,
    handler: Handler,
    stage: str,
    attempt_id: uuid.UUID,
) -> None:
    """Возвращает управление только после того, как offset подтверждён (см.
    инвариант в докстринге модуля)."""
    loop = asyncio.get_event_loop()
    attempt = 0
    pause_cycles = 0
    paused = False
    # Дедлайн удержания партиции из-за недоступной DLQ (None — пока
    # такого не случалось).
    dlq_hold_deadline: float | None = None
    try:
        while True:
            # Проверяем дедлайн на каждой итерации, а не только в ветке
            # ниже: один цикл ретраев может сам по себе растянуться
            # (ожидание недоступного Postgres), а просрочить бюджет нельзя
            # — за ним aiokafka выведет консьюмера из группы.
            if dlq_hold_deadline is not None and loop.time() >= dlq_hold_deadline:
                raise DlqUnavailableError(
                    f"DLQ unavailable for "
                    f"{settings.dlq_unavailable_max_hold_seconds}s, giving up the "
                    f"partition instead of committing an unrecorded message "
                    f"(topic={record.topic} partition={record.partition} "
                    f"offset={record.offset})"
                )
            attempt += 1
            try:
                await handler(record, attempt_id)
                await consumer.commit({tp: record.offset + 1})
                return
            except DlqUnavailableError as exc:
                # Обработчик не смог сохранить причину сбоя (БД
                # недоступна) и при этом уже выполнил необратимое действие
                # (send_service: письмо, возможно, ушло). Повторять его
                # нельзя — с тем же attempt_id это был бы дубль письма, —
                # а коммитить нечего: причина нигде не записана. Роняем
                # процесс с неподтверждённым offset'ом: после рестарта
                # attempt_id другой, и сообщение уйдёт на ручной разбор.
                logger.critical(
                    f"Handler could not record the outcome, NOT committing "
                    f"message (topic={record.topic} partition={record.partition} "
                    f"offset={record.offset}): {exc}"
                )
                raise
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
                    if await _give_up(record, stage, exc):
                        await consumer.commit({tp: record.offset + 1})
                        return

                    # DLQ недоступна — offset не подтверждаем и держим
                    # партицию на паузе. Следующий цикл (attempt = 0) снова
                    # пробует handler: если Postgres успел подняться,
                    # уведомление будет доставлено по-настоящему, а не
                    # списано в DLQ.
                    if dlq_hold_deadline is None:
                        dlq_hold_deadline = (
                            loop.time() + settings.dlq_unavailable_max_hold_seconds
                        )
                    if not paused:
                        consumer.pause(tp)
                        paused = True
                    # Спать дольше остатка бюджета бессмысленно — проверка
                    # в начале следующей итерации всё равно сдастся.
                    await asyncio.sleep(
                        max(
                            0.0,
                            min(
                                settings.partition_pause_seconds,
                                dlq_hold_deadline - loop.time(),
                            ),
                        )
                    )
                    attempt = 0
                    continue

                logger.error(
                    f"Exhausted retries for partition {record.partition} "
                    f"(offset={record.offset}), pausing for "
                    f"{settings.partition_pause_seconds}s before retrying again "
                    f"(pause cycle {pause_cycles}/{settings.max_pause_cycles}): {exc}"
                )
                if not paused:
                    consumer.pause(tp)
                    paused = True
                await asyncio.sleep(settings.partition_pause_seconds)
                _resume_quietly(consumer, tp)
                paused = False
                attempt = 0
                continue
    finally:
        if paused:
            _resume_quietly(consumer, tp)
