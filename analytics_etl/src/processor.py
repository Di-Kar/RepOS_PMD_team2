"""Группировка в пакеты, удаление дубликатов и маршрутизация проверенных событий."""

import json
import logging
from typing import Dict, List, Tuple

from loader import ClickHouseLoader
from transformer import (
    EVENTS_TABLE,
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
        # Буферы строк по таблицам (заполняются при flush)
        self._events_rows: List[dict] = []
        self._movies_rows: List[dict] = []
        self._watch_rows: List[dict] = []
        self._flushed_count = 0
        # Буфер событий (event_id → event)
        self._buffer: Dict[str, dict] = {}
        # Смещения, ожидающие коммита после успешной вставки в ClickHouse: {topic: {partition: offset}}
        self._pending_offsets: Dict[str, Dict[int, int]] = {}

    @property
    def buffer_size(self) -> int:
        """Количество событий без дубликатов в буфере."""
        return len(self._buffer)

    def add_event(
        self,
        validated_event: dict,
        topic: str = None,
        partition: int = None,
        offset: int = None,
    ) -> None:
        """Добавить проверенное событие в буфер в памяти.

        Если ``event_id`` уже существует, новое событие заменяет старое
        только если у него более позднее время ``occurred_at``.

        При передаче topic/partition/offset смещение добавляется в
        ``_pending_offsets`` для последующего коммита после успешной
        вставки в ClickHouse.
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

        # Отслеживать смещение, ожидающее коммита
        if topic and partition is not None and offset is not None:
            if topic not in self._pending_offsets:
                self._pending_offsets[topic] = {}
            # offset + 1 — следующее сообщение для чтения
            self._pending_offsets[topic][partition] = offset + 1

    def flush(self) -> Tuple[int, bool]:
        """Отправить все буферизованные события в ClickHouse / DLQ.

        Возвращает кортеж ``(count, success)``:
        - ``count`` — количество вставленных строк
        - ``success`` — True только если ВСЕ вставки прошли успешно

        Буфер очищается только при успешной вставке; при ошибке события
        остаются в буфере для повторной попытки.
        """
        if not self._buffer:
            return (0, True)

        logger.info(
            'Отправляю %d событий в ClickHouse (без дубликатов)', len(self._buffer)
        )

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
                    event_id,
                    e,
                )
                self._dlq.write(
                    event_id=event_id,
                    event_type=event.get('event_type', 'unknown'),
                    error_type='TRANSFORM_ERROR',
                    error_message=str(e),
                    raw_event=json.dumps(event, ensure_ascii=False),
                )

        total_processed = 0

        # Отслеживаем успех каждой вставки
        events_success = True
        movies_success = True
        watch_success = True

        # Вставка в таблицу events
        if self._events_rows:
            events_success = self._try_insert(EVENTS_TABLE, self._events_rows)
            if events_success:
                total_processed += len(self._events_rows)

        # Вставка в таблицу movies_metrics
        if self._movies_rows:
            movies_success = self._try_insert_movies_metrics(self._movies_rows)
            if movies_success:
                total_processed += len(self._movies_rows)

        # Вставка в таблицу watch_sessions
        if self._watch_rows:
            watch_success = self._try_insert_watch_sessions(self._watch_rows)
            if watch_success:
                total_processed += len(self._watch_rows)

        # Успех только если ВСЕ непустые вставки прошли успешно
        all_success = events_success and movies_success and watch_success

        if all_success:
            # Очистить буфер иpending offsets только при успешной вставке
            self._buffer.clear()
            self._flushed_count += 1
            logger.info(
                'Flush #%d завершён: вставлено %d строк всего',
                self._flushed_count,
                total_processed,
            )
            return (total_processed, True)
        else:
            # При ошибке НЕ очищаем буфер — события останутся для повторной попытки
            logger.warning(
                'Flush #%d НЕ УДАЛСЯ: в буфере %d событий, смещения не коммитим',
                self._flushed_count + 1,
                len(self._buffer),
            )
            return (total_processed, False)

    @property
    def pending_offsets(self) -> Dict[str, Dict[int, int]]:
        """Возвращает смещения, ожидающие коммита в Kafka.

        Эти смещения будут зафиксированы только после успешной вставки
        всех событий из буфера в ClickHouse.
        """
        return {k: dict(v) for k, v in self._pending_offsets.items()}

    def clear_committed_offsets(self) -> None:
        """Очистить pending offsets после успешного коммита в Kafka."""
        self._pending_offsets.clear()

    def _try_insert(self, table: str, rows: List[dict]) -> bool:
        """Вставить строки в таблицу ClickHouse с обработкой ошибок.

        Возвращает True при успехе, False после исчерпания попыток retry
        (после чего строки направляются в DLQ).
        """
        try:
            self._loader.bulk_insert(table, rows)
            return True
        except Exception as e:
            logger.error(
                'Исчерпаны все попытки вставки %d строк в %s: %s',
                len(rows),
                table,
                e,
            )
            # Направить неудавшиеся строки в DLQ
            for row in rows:
                try:
                    self._dlq.write(
                        event_id=row.get('event_id', 'unknown'),
                        event_type=row.get('event_type', 'unknown'),
                        error_type='INSERT_ERROR',
                        error_message=f'Не удалось вставить в {table}: {e}',
                        raw_event=row.get(
                            'raw_event', json.dumps(row, ensure_ascii=False)
                        ),
                    )
                except Exception as dlq_error:
                    logger.critical(
                        'Не удалось записать в DLQ для event_id=%s: %s',
                        row.get('event_id', 'unknown'),
                        dlq_error,
                    )
            return False

    def _try_insert_movies_metrics(self, rows: List[dict]) -> bool:
        """Вставить агрегированные строки метрик фильмов.

        Возвращает True при успехе, False после исчерпания попыток retry.
        """
        try:
            self._loader.bulk_insert_movies_metrics(rows)
            return True
        except Exception as e:
            logger.error(
                'Исчерпаны все попытки вставки метрик фильмов: %s',
                e,
            )
            return False

    def _try_insert_watch_sessions(self, rows: List[dict]) -> bool:
        """Вставить строки сеансов просмотра.

        Возвращает True при успехе, False после исчерпания попыток retry.
        """
        try:
            self._loader.bulk_insert_watch_sessions(rows)
            return True
        except Exception as e:
            logger.error(
                'Исчерпаны все попытки вставки сеансов просмотра: %s',
                e,
            )
            return False
