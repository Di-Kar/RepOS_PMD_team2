"""Сервис аналитического ETL: потребитель Kafka → запись в ClickHouse.

Считывает данные из трёх топиков Kafka (клики, просмотры страниц,
пользовательские события), проверяет, преобразует, группирует в пакеты
и записывает в таблицы ClickHouse. Смещения (offsets) фиксируются
вручную после успешной доставки пакета.
"""

import json
import logging
import os
import signal
import sys
import time

from config import (
    clickhouse_settings,
    etl_settings,
    kafka_settings,
)
from backoff_utils import configure as configure_backoff
from dlq import DeadLetterQueue
from loader import ClickHouseLoader
from memory_monitor import MemoryMonitor
from processor import EventProcessor
from state import OffsetStorage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

# Флаг для корректного завершения работы
_running = True


def _signal_handler(signum, frame):
    """Обработка сигналов SIGINT / SIGTERM для корректного завершения."""
    global _running
    logger.info('Получен сигнал %s — запускаю корректное завершение', signum)
    _running = False


# Регистрация обработчиков сигналов
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def run_etl():
    """Основной цикл ETL: чтение из Kafka, проверка, преобразование, запись."""
    global _running

    # Настройка параметров повторных попыток
    configure_backoff(
        start_sleep_time=etl_settings.backoff_start,
        border_sleep_time=etl_settings.backoff_border,
        max_attempts=etl_settings.backoff_max,
    )

    # --- Инициализация ---
    # Создать директорию для состояния
    os.makedirs(etl_settings.state_dir, exist_ok=True)

    # Управление состоянием
    storage = OffsetStorage(etl_settings.state_dir)
    storage.load_state()  # инициализировать кэш состояния
    logger.info('Директория для хранения текущего состояния: %s', etl_settings.state_dir)

    # Загрузчик ClickHouse
    loader = ClickHouseLoader(
        host=clickhouse_settings.host,
        port=clickhouse_settings.port,
        database=clickhouse_settings.database,
        user=clickhouse_settings.user,
        password=clickhouse_settings.password,
    )
    loader.ensure_database_exists()

    # Загрузка и выполнение схемы
    schema_file = os.path.join(os.path.dirname(__file__), 'schema.sql')
    try:
        loader.init_schema(schema_file)
    except Exception as e:
        logger.warning('Инициализация схемы вызвала проблемы (может уже существует): %s', e)

    # DLQ
    dlq = DeadLetterQueue(loader)

    # Обработчик событий
    processor = EventProcessor(loader, dlq)

    # Мониторинг памяти
    mem_monitor = MemoryMonitor(
        warn_mb=etl_settings.memory_warn_mb,
        critical_mb=etl_settings.memory_critical_mb,
    )

    # Импортировать потребителя Kafka здесь, чтобы он загружался только во время выполнения
    from confluent_kafka import Consumer, KafkaError, Message

    # Потребитель Kafka — ручная фиксация смещений
    kafka_conf = {
        'bootstrap.servers': kafka_settings.bootstrap_servers,
        'group.id': kafka_settings.consumer_group,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
        'enable.auto.offset.store': False,
        'session.timeout.ms': '10000',
        'max.poll.interval.ms': '300000',
        'partition.assignment.strategy': 'cooperative-sticky',
    }
    consumer = Consumer(kafka_conf)
    topics = kafka_settings.topics_list
    logger.info('Подписка на топики: %s', ', '.join(topics))
    consumer.subscribe(topics)

    last_flush_time = time.time()
    poll_timeout = 1.0  # секунд между опросами
    last_mem_check = 0

    try:
        while _running:
            now = time.time()

            # Периодическая проверка памяти (каждые 30с)
            if now - last_mem_check > 30:
                status = mem_monitor.check_thresholds()
                if status == 'critical':
                    mem_monitor.auto_gc()
                last_mem_check = now

            # Ожидание сообщений Kafka
            msg = consumer.poll(timeout=poll_timeout)

            if msg is None:
                # Проверить flush интервал
                if now - last_flush_time >= etl_settings.flush_interval:
                    processed = processor.flush()
                    if processed:
                        _commit_offsets(consumer, processor)
                    last_flush_time = now
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.debug(
                        'Конец раздела [%s]://%d на offset %d',
                        msg.topic(), msg.partition(), msg.offset(),
                    )
                else:
                    logger.error('Ошибка Kafka: %s', msg.error())
                continue

            # Обработка сообщения
            _process_message(msg, processor, consumer)

            # Проверить flush интервал
            if now - last_flush_time >= etl_settings.flush_interval:
                processed = processor.flush()
                if processed:
                    _commit_offsets(consumer, processor)
                last_flush_time = now

    except KeyboardInterrupt:
        logger.info('Прервано клавиатурой — завершение работы')
    finally:
        logger.info('Финальная отправка %d буферизованных событий', processor.buffer_size)
        processor.flush()
        _commit_offsets(consumer, processor)
        consumer.close()
        logger.info('ETL остановлен')


def _process_message(msg, processor, consumer):
    """Проверить и буферизовать одно сообщение Kafka."""
    try:
        raw_payload = msg.value().decode('utf-8')
        raw_event = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(
            'Не удалось декодировать сообщение в [%s]://%d offset %d: %s',
            msg.topic(), msg.partition(), msg.offset(), e,
        )
        consumer.store_offsets(msg)
        return
    except Exception as e:
        logger.error('Ошибка обработки сообщения в [%s]://%d offset %d: %s',
                     msg.topic(), msg.partition(), msg.offset(), e)
        consumer.store_offsets(msg)
        return

    # Валидация
    from validator import validate_event
    validated = validate_event(raw_event)

    if validated is None:
        # Недопустимое событие — направить в DLQ
        logger.warning(
            'Недопустимое событие в [%s]://%d offset %d — отправка в DLQ',
            msg.topic(), msg.partition(), msg.offset(),
        )
        _route_to_dlq(msg, raw_event, consumer)
        return

    # Сохранить валидированное событие в буфер
    processor.add_event(validated)

    # Зафиксировать смещение сразу после обработки
    consumer.store_offsets(msg)


def _route_to_dlq(msg, raw_event, consumer):
    """Направить недопустимое событие в DLQ и зафиксировать его смещение."""
    _dlq = DeadLetterQueue(ClickHouseLoader(
        host=clickhouse_settings.host,
        port=clickhouse_settings.port,
        database=clickhouse_settings.database,
        user=clickhouse_settings.user,
        password=clickhouse_settings.password,
    ))

    try:
        _dlq.write(
            event_id=str(raw_event.get('event_id', 'unknown')),
            event_type=str(raw_event.get('event_type', 'unknown')),
            error_type='VALIDATION_ERROR',
            error_message='Событие не прошло проверки валидации',
            raw_event=json.dumps(raw_event, ensure_ascii=False),
        )
    except Exception as e:
        logger.error('Не удалось записать в DLQ: %s', e)

    consumer.store_offsets(msg)


def _commit_offsets(consumer, processor):
    """Зафиксировать смещения в файле состояния."""
    try:
        offsets = consumer.offsets_stored()
        if not offsets:
            return

        # Преобразовать в словарь для хранения состояния: {topic: {partition: offset}}
        offset_dict = {}
        for tp in offsets:
            topic = tp.topic
            partition = tp.partition
            offset = tp.offset
            if topic not in offset_dict:
                offset_dict[topic] = {}
            offset_dict[topic][partition] = offset

        storage = OffsetStorage(etl_settings.state_dir)
        storage.save_offsets(offset_dict)
        logger.debug('Смещения зафиксированы: %d тем', len(offset_dict))
    except Exception as e:
        logger.error('Не удалось зафиксировать смещения: %s', e)


if __name__ == '__main__':
    logger.info('Запускаю сервис Analytics ETL')
    logger.info('Серверы Kafka: %s', kafka_settings.bootstrap_servers)
    logger.info('ClickHouse: %s:%d/%s',
                clickhouse_settings.host, clickhouse_settings.port,
                clickhouse_settings.database)
    logger.info('Темы: %s', ', '.join(kafka_settings.topics_list))
    logger.info('Размер пакета: %d, Интервал отправки: %ds',
                etl_settings.batch_size, etl_settings.flush_interval)
    run_etl()
