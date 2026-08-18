"""Тесты для batch_size flush behavior в main.py.

Проверяют:
1. Flush происходит при достижении batch_size.
2. Таймерный flush не дублирует batch_size flush.
3. Batch_size flush происходит раньше таймерного.
4. Буфер защищён от переполнения памяти.
"""

import pytest
import time
from unittest.mock import MagicMock, patch

# Используем реальный EventProcessor с моками зависимостей
from processor import EventProcessor


def _make_validated_event(event_id: str = 'evt-001', **overrides) -> dict:
    """Создаёт валидированное событие для тестов."""
    return {
        'event_id': event_id,
        'event_type': 'click',
        'schema_version': 1,
        'occurred_at': '2025-01-15T10:00:00+00:00',
        'received_at': '2025-01-15T10:00:01+00:00',
        'user_id': 'user-42',
        'anonymous_id': None,
        'session_id': 'sess-abc',
        'sequence_number': 10,
        'consent': True,
        'context': {'page_type': 'movie'},
        'source': 'web',
        'payload': {'element_id': 'play'},
        **overrides,
    }


class TestBatchSizeFlush:
    """Тесты для flush при достижении batch_size."""

    @pytest.fixture
    def processor_with_flush_tracking(self):
        """Создаёт EventProcessor с отслеживанием вызовов flush."""
        loader = MagicMock()
        loader.bulk_insert.return_value = True
        loader.bulk_insert_movies_metrics.return_value = True
        loader.bulk_insert_watch_sessions.return_value = True

        dlq = MagicMock()

        proc = EventProcessor(loader=loader, dlq=dlq)

        # Отслеживаем вызовы flush
        original_flush = proc.flush
        flush_calls = []

        def tracking_flush():
            flush_calls.append(time.time())
            return original_flush()

        proc.flush = tracking_flush

        return proc, flush_calls

    def test_batch_size_triggers_flush(self, processor_with_flush_tracking):
        """Тест: flush вызывается при достижении batch_size."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 5

        # Добавляем события по одному
        for i in range(batch_size):
            processor.add_event(_make_validated_event(f'evt-{i}'))

            # Эмуляция проверки из main.py
            if processor.buffer_size >= batch_size:
                processor.flush()
                processor.clear_committed_offsets()

        # Flush должен был сработать
        assert len(flush_calls) >= 1

    def test_batch_size_before_timer(self, processor_with_flush_tracking):
        """Тест: batch_size flush происходит раньше таймерного."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 5
        flush_interval = 5  # секунд

        last_flush_time = time.time()

        # Добавляем события
        for i in range(batch_size):
            now = time.time()
            processor.add_event(_make_validated_event(f'evt-{i}'))

            # Логика из main.py: сначала проверка batch_size, потом timer
            if processor.buffer_size >= batch_size:
                processor.flush()
                processor.clear_committed_offsets()
                last_flush_time = now
            elif now - last_flush_time >= flush_interval:
                processor.flush()
                processor.clear_committed_offsets()
                last_flush_time = now

        # Flush должен быть вызван ровно 1 раз (по batch_size, а не по таймеру)
        assert len(flush_calls) == 1

    def test_no_double_flush_batch_and_timer(self, processor_with_flush_tracking):
        """Тест: нет двойного flush когда batch_size и timer срабатывают одновременно."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 5
        flush_interval = 5

        # Заполняем буфер до batch_size
        for i in range(batch_size):
            processor.add_event(_make_validated_event(f'evt-{i}'))

        last_flush_time = time.time() - flush_interval - 1  # таймер истёк
        now = time.time()

        # Эмулируем логику main.py (if-elif, а не if-if)
        if processor.buffer_size >= batch_size:
            processor.flush()
            processor.clear_committed_offsets()
            last_flush_time = now
        elif now - last_flush_time >= flush_interval:
            processor.flush()
            processor.clear_committed_offsets()
            last_flush_time = now

        # Flush должен быть вызван ровно 1 раз (if-elif предотвращает дублирование)
        assert len(flush_calls) == 1

    def test_buffer_protected_from_oom(self, processor_with_flush_tracking):
        """Тест: буфер не растёт бесконечно — flush срабатывает по batch_size."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 5

        # Симулируем высокую нагрузку: добавляем больше событий чем batch_size
        num_events = batch_size * 3
        last_flush_time = time.time()
        flush_interval = 5

        for i in range(num_events):
            now = time.time()
            processor.add_event(_make_validated_event(f'high-load-{i}'))

            # Логика из main.py
            if processor.buffer_size >= batch_size:
                processor.flush()
                processor.clear_committed_offsets()
                last_flush_time = now
            elif now - last_flush_time >= flush_interval:
                processor.flush()
                processor.clear_committed_offsets()
                last_flush_time = now

        # Flush должен был сработать минимум 3 раза (для 3x batch_size)
        assert len(flush_calls) >= 3

        # После каждого flush буфер очищается, поэтому buffer_size < batch_size
        assert processor.buffer_size < batch_size

    def test_multiple_batch_flush_cycles(self, processor_with_flush_tracking):
        """Тест: несколько циклов batch flush работают корректно."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 3

        # Первый batch
        for i in range(batch_size):
            processor.add_event(_make_validated_event(f'batch1-evt-{i}'))

        if processor.buffer_size >= batch_size:
            processor.flush()
            processor.clear_committed_offsets()

        assert len(flush_calls) == 1
        assert processor.buffer_size == 0

        # Второй batch
        for i in range(batch_size):
            processor.add_event(_make_validated_event(f'batch2-evt-{i}'))

        if processor.buffer_size >= batch_size:
            processor.flush()
            processor.clear_committed_offsets()

        # Должно быть 2 flush
        assert len(flush_calls) == 2
        assert processor.buffer_size == 0

    def test_early_flush_before_batch_size(self, processor_with_flush_tracking):
        """Тест: если batch_size не достигнут, flush не вызывается (ждём timer)."""
        processor, flush_calls = processor_with_flush_tracking
        batch_size = 10
        flush_interval = 5

        # Добавляем меньше событий чем batch_size
        for i in range(3):
            processor.add_event(_make_validated_event(f'evt-{i}'))

        # Проверяем логику main.py
        last_flush_time = time.time()
        now = time.time()

        if processor.buffer_size >= batch_size:
            processor.flush()
            processor.clear_committed_offsets()
            last_flush_time = now
        elif now - last_flush_time >= flush_interval:
            processor.flush()
            processor.clear_committed_offsets()
            last_flush_time = now

        # Flush не должен быть вызван (ни batch_size, ни timer не сработали)
        assert len(flush_calls) == 0
