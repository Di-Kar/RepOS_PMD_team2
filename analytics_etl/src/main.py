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
from confluent_kafka import TopicPartition
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

    # Initial poll to trigger partition assignment
    assigned = consumer.poll(timeout=5.0)
    logger.info('Инициализация назначения партиций: получено %d сообщений', assigned)

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
                    processed, success = processor.flush()
                    if processed and success:
                        _commit_offsets(consumer, processor)
                        processor.clear_committed_offsets()
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
            _process_message(msg, processor, consumer, dlq)

            # Проверить flush интервал
            if now - last_flush_time >= etl_settings.flush_interval:
                processed, success = processor.flush()
                if processed and success:
                    _commit_offsets(consumer, processor)
                    processor.clear_committed_offsets()
                last_flush_time = now

    except KeyboardInterrupt:
        logger.info('Прервано клавиатурой — завершение работы')
    finally:
        logger.info('Финальная отправка %d буферизованных событий', processor.buffer_size)
        processed, success = processor.flush()
        if processed and success:
            _commit_offsets(consumer, processor)
            processor.clear_committed_offsets()
        consumer.close()
        loader.close()
        logger.info('ETL остановлен')


def _track_offset(processor, msg):
    """Добавить смещение в pending_offsets для последующего коммита."""
    topic = msg.topic()
    partition = msg.partition()
    offset = msg.offset()
    if topic not in processor._pending_offsets:
        processor._pending_offsets[topic] = {}
    processor._pending_offsets[topic][partition] = offset + 1


def _process_message(msg, processor, consumer, dlq):
    """Проверить и буферизовать одно сообщение Kafka."""
    try:
        # Сохраняем сырое значение до обработки — для DLQ в случае ошибки
        raw_value = msg.value()
        raw_payload = raw_value.decode('utf-8') if raw_value else ''
        raw_event = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning(
            'Не удалось декодировать сообщение в [%s]://%d offset %d: %s',
            msg.topic(), msg.partition(), msg.offset(), e,
        )
        # Событие некорректно — направляем в DLQ и фиксируем смещение,
        # так как оно не попадёт в буфер и не потребится повторно
        try:
            raw_payload_str = (
                raw_value.decode('utf-8', errors='replace')
                if isinstance(raw_value, bytes) and raw_value
                else str(raw_value) if raw_value else ''
            )
        except Exception:
            raw_payload_str = ''
        _route_to_dlq(msg, {
            'raw_message': raw_payload_str,
            'error_type': 'DECODE_ERROR',
            'error_message': str(e),
        }, dlq)
        _track_offset(processor, msg)
        return
    except Exception as e:
        logger.error('Ошибка обработки сообщения в [%s]://%d offset %d: %s',
                     msg.topic(), msg.partition(), msg.offset(), e)
        # Отправляем сырое сообщение в DLQ — данные не должны теряться
        try:
            raw_payload_str = (
                raw_value.decode('utf-8', errors='replace')
                if isinstance(raw_value, bytes) and raw_value
                else str(raw_value) if raw_value else ''
            )
        except Exception:
            raw_payload_str = ''
        _route_to_dlq(msg, {
            'raw_message': raw_payload_str,
            'error_type': 'PROCESSING_ERROR',
            'error_message': str(e),
        }, dlq)
        _track_offset(processor, msg)
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
        _route_to_dlq(msg, raw_event, dlq)
        # Событие отправлено в DLQ — фиксируем смещение немедленно
        _track_offset(processor, msg)
        return

    # Сохранить валидированное событие в буфер
    processor.add_event(validated)
    _track_offset(processor, msg)


def _route_to_dlq(msg, raw_event, dlq):
    """Направить недопустимое событие в DLQ.

    Поддерживает два сценария:
    1. Валидационная ошибка: raw_event — оригинальное событие
    2. Ошибка обработки: raw_event — словарь с ключами
       'raw_message', 'error_type', 'error_message'
    """
    try:
        if 'error_message' in raw_event and 'raw_message' in raw_event:
            # Ошибка обработки — отправляем сырое сообщение
            dlq.write(
                event_id=str(raw_event.get('event_id', 'unknown')),
                event_type=str(raw_event.get('event_type', 'unknown')),
                error_type=raw_event.get('error_type', 'UNKNOWN_ERROR'),
                error_message=raw_event.get('error_message', 'Unknown error'),
                raw_event=raw_event.get('raw_message', ''),
            )
        else:
            # Валидационная ошибка — отправляем разобранное событие
            dlq.write(
                event_id=str(raw_event.get('event_id', 'unknown')),
                event_type=str(raw_event.get('event_type', 'unknown')),
                error_type='VALIDATION_ERROR',
                error_message='Событие не прошло проверку валидации',
                raw_event=json.dumps(raw_event, ensure_ascii=False),
            )
    except Exception as e:
        logger.error('Не удалось записать в DLQ: %s', e)


def _commit_offsets(consumer, processor):
    """Зафиксировать pending смещения в Kafka и сохранить в файл состояния.
    
    Вызывается ТОЛЬКО после успешной вставки всех событий в ClickHouse.
    Смещения коммитятся только для тех событий, которые были реально записаны.
    
    Использует consumer.assignment() для получения корректного списка 
    назначенных партиций и валидации topic-partition перед коммитом.
    """
    try:
        offsets_to_commit = processor.pending_offsets
        if not offsets_to_commit:
            return

        # Получаем назначенные партиции через consumer.assignment()
        assigned_partitions = consumer.assignment()
        
        # Фильтруем смещения: коммитим только для назначенных партиций
        commit_list = []
        for tp in assigned_partitions:
            if tp.topic in offsets_to_commit:
                if tp.partition in offsets_to_commit[tp.topic]:
                    offset = offsets_to_commit[tp.topic][tp.partition]
                    commit_list.append(TopicPartition(tp.topic, tp.partition, offset))
        
        if commit_list:
            consumer.commit(offsets=commit_list)

        # Сохранить смещения в файл состояния
        storage = OffsetStorage(etl_settings.state_dir)
        storage.save_offsets(offsets_to_commit)
        logger.debug('Смещения зафиксированы: %d тем', len(offsets_to_commit))
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
