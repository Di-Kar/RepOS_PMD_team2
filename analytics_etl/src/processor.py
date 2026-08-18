"""Группировка в пакеты, удаление дубликатов и маршрутизация проверенных событий."""

import json
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from backoff_utils import backoff
from config import etl_settings
from loader import ClickHouseLoader
from transformer import (
    EVENTS_TABLE,
    MOVIES_METRICS_TABLE,
    WATCH_SESSIONS_TABLE,
    transform_for_events,
    transform_for_movies_metrics,
    transform_for_watch_sessions,
)

logger = logging.getLogger(__name__)


class EventProcessor:
    """Управление группировкой в пакеты, удалением дубликатов и маршрутизацией событий.

    События хранятся в буферах в памяти, сгруппированных по целевой таблице.
    Удаление дубликатов выполняется по ``event_id`` — при обнаружении дубликата
    сохраняется только последнее событие (с самым поздним ``occurred_at``).

    При отправке строки вставляются в ClickHouse через ``ClickHouseLoader``,
    а недопустимые события направляются в очередь DLQ через ``DeadLetterQueue``.
    """

    def __init__(self, loader: ClickHouseLoader, dlq):
        self._loader = loader
        self._dlq = dlq
        # event_id → словарь события (побеждает позднее)
        self._buffer: Dict[str, dict] = {}
        # Буферы строк по таблицам (заполняются при flush)
        self._events_rows: List[dict] = []
        self._movies_rows: List[dict] = []
        self._watch_rows: List[dict] = []
        self._flushed_count = 0
        # Последние зафиксированные смещения Kafka: {topic: {partition: offset}}
        self._last_offsets: Dict[str, Dict[int, int]] = {}

    @property
    def buffer_size(self) -> int:
        """Количество событий без дубликатов в буфере."""
        return len(self._buffer)

    def add_event(self, validated_event: dict) -> None:
        """Добавить проверенное событие в буфер в памяти.

        Если ``event_id`` уже существует, новое событие заменяет старое
        только если у него более позднее время ``occurred_at``.
        """
        event_id = str(validated_event['event_id'])
        occurred_at = validated_event.get('occurred_at', '')

        if event_id in self._buffer:
            existing_at = self._buffer[event_id].get('occurred_at', '')
            # Оставить событие с более поздним occurred_at
            if occurred_at >= existing_at:
                self._buffer[event_id] = validated_event
            return

        self._buffer[event_id] = validated_event

    def flush(self) -> int:
        """Отправить все буферизованные события в ClickHouse / DLQ.

        Возвращает количество успешно обработанных строк.
        """
        if not self._buffer:
            return 0

        logger.info('Отправляю %d событий в ClickHouse (без дубликатов)', len(self._buffer))

        self._events_rows = []
        self._movies_rows = []
        self._watch_rows = []

        for event_id, event in self._buffer.items():
            try:
                # Преобразовать в таблицу events
                events_row = transform_for_events(event)
                self._events_rows.append(events_row)

                # Преобразовать в movies_metrics (необязательно)
                movie_row = transform_for_movies_metrics(event)
                if movie_row:
                    self._movies_rows.append(movie_row)

                # Преобразовать в watch_sessions (необязательно)
                watch_row = transform_for_watch_sessions(event)
                if watch_row:
                    self._watch_rows.append(watch_row)

            except Exception as e:
                logger.error(
                    'Ошибка преобразования для event_id=%s: %s. Отправляю в DLQ.',
                    event_id, e,
                )
                self._dlq.write(
                    event_id=event_id,
                    event_type=event.get('event_type', 'unknown'),
                    error_type='TRANSFORM_ERROR',
                    error_message=str(e),
                    raw_event=json.dumps(event, ensure_ascii=False),
                )

        total_processed = 0

        # Вставка в таблицу events
        if self._events_rows:
            if self._try_insert(EVENTS_TABLE, self._events_rows):
                total_processed += len(self._events_rows)

        # Вставка в таблицу movies_metrics
        if self._movies_rows:
            if self._try_insert_movies_metrics(self._movies_rows):
                total_processed += len(self._movies_rows)

        # Вставка в таблицу watch_sessions
        if self._watch_rows:
            if self._try_insert_watch_sessions(self._watch_rows):
                total_processed += len(self._watch_rows)

        # Очистить буфер
        self._buffer.clear()
        self._flushed_count += 1
        logger.info(
            'Flush #%d завершён: вставлено %d строк всего',
            self._flushed_count, total_processed,
        )
        return total_processed

    @property
    def last_offsets(self) -> Dict[str, Dict[int, int]]:
        """Возвращает последние зафиксированные смещения Kafka."""
        return {k: dict(v) for k, v in self._last_offsets.items()}

    def _try_insert(self, table: str, rows: List[dict]) -> bool:
        """Вставить строки в таблицу ClickHouse с обработкой ошибок."""
        try:
            success = self._loader.bulk_insert(table, rows)
            if not success:
                logger.error('Не удалось вставить %d строк в %s', len(rows), table)
                # Направить неудавшиеся строки в DLQ
                for row in rows:
                    self._dlq.write(
                        event_id=row.get('event_id', 'unknown'),
                        event_type=row.get('event_type', 'unknown'),
                        error_type='INSERT_ERROR',
                        error_message=f'Не удалось вставить в {table}',
                        raw_event=row.get('raw_event', json.dumps(row, ensure_ascii=False)),
                    )
            return success
        except Exception as e:
            logger.error('Исключение при вставке в %s: %s', table, e)
            return False

    def _try_insert_movies_metrics(self, rows: List[dict]) -> bool:
        """Вставить агрегированные строки метрик фильмов."""
        try:
            success = self._loader.bulk_insert_movies_metrics(rows)
            if not success:
                logger.error('Не удалось вставить %d строк в movies_metrics', len(rows))
            return success
        except Exception as e:
            logger.error('Исключение при вставке в movies_metrics: %s', e)
            return False

    def _try_insert_watch_sessions(self, rows: List[dict]) -> bool:
        """Вставить строки сеансов просмотра."""
        try:
            success = self._loader.bulk_insert_watch_sessions(rows)
            if not success:
                logger.error('Не удалось вставить %d строк в watch_sessions', len(rows))
            return success
        except Exception as e:
            logger.error('Исключение при вставке в watch_sessions: %s', e)
            return False
