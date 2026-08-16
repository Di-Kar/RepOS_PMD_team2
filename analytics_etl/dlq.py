"""Обработчик DLQ для недопустимых событий.

Записывает отклонённые события в таблицу ClickHouse ``dead_letter_queue``
для последующего расследования.
"""

import json
import logging
import time
from typing import Optional

from analytics_etl.backoff_utils import backoff
from analytics_etl.loader import ClickHouseLoader, _CLICKHOUSE_EXCEPTIONS

logger = logging.getLogger(__name__)

DLQ_TABLE = 'dead_letter_queue'


class DeadLetterQueue:
    """Записывает невалидные события в очередь DLQ ClickHouse."""

    def __init__(self, loader: ClickHouseLoader):
        self._loader = loader
        self._buffer: list[dict] = []

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def write(
        self,
        event_id: str,
        event_type: str,
        error_type: str,
        error_message: str,
        raw_event: str,
    ) -> None:
        """Записать одно событие в DLQ.
        """
        self._do_write(event_id, event_type, error_type, error_message, raw_event)

    @backoff(exceptions=_CLICKHOUSE_EXCEPTIONS)
    def _do_write(
        self,
        event_id: str,
        event_type: str,
        error_type: str,
        error_message: str,
        raw_event: str,
    ) -> None:
        """Основная логика записи (обёрнута backoff)."""
        loader = self._loader._get_client()
        data = [[event_id, event_type, error_type, error_message, raw_event]]
        loader.insert(
            DLQ_TABLE,
            data,
            column_names=['event_id', 'event_type', 'error_type', 'error_message', 'raw_event'],
            database=self._loader.database,
        )
        logger.warning(
            'DLQ: event_id=%s type=%s error=%s: %s',
            event_id, event_type, error_type, error_message[:100],
        )

    def write_batch(self, events: list[dict]) -> int:
        """Записать пакет записей DLQ одновременно.

        Каждый словарь в ``events`` должен иметь ключи:
        event_id, event_type, error_type, error_message, raw_event
        """
        if not events:
            return 0

        data = [
            [
                e.get('event_id', ''),
                e.get('event_type', ''),
                e.get('error_type', ''),
                e.get('error_message', ''),
                e.get('raw_event', ''),
            ]
            for e in events
        ]

        loader = self._loader._get_client()
        loader.insert(
            DLQ_TABLE,
            data,
            column_names=['event_id', 'event_type', 'error_type', 'error_message', 'raw_event'],
            database=self._loader.database,
        )
        logger.info('DLQ: записано %d событий', len(events))
        return len(events)
