"""Unit-tests для analytics_etl.processor — EventProcessor с моками."""

from unittest.mock import MagicMock

import pytest
from processor import EventProcessor

# --------------------------------------------------------------------------- #
#  Фикстуры / helpers                                                          #
# --------------------------------------------------------------------------- #


def _make_validated_event(
    event_id: str = 'evt-001',
    event_type: str = 'click',
    occurred_at: str = '2025-01-15T10:00:00+00:00',
    user_id: str = 'user-42',
    **overrides,
) -> dict:
    return {
        'event_id': event_id,
        'event_type': event_type,
        'schema_version': 1,
        'occurred_at': occurred_at,
        'received_at': '2025-01-15T10:00:01+00:00',
        'user_id': user_id,
        'anonymous_id': None,
        'session_id': 'sess-abc',
        'sequence_number': 10,
        'consent': True,
        'context': {'page_type': 'movie'},
        'source': 'web',
        'payload': {'element_id': 'play'},
        **overrides,
    }


@pytest.fixture
def mock_loader():
    loader = MagicMock()
    loader.bulk_insert.return_value = True
    loader.bulk_insert_movies_metrics.return_value = True
    loader.bulk_insert_watch_sessions.return_value = True
    return loader


@pytest.fixture
def mock_dlq():
    return MagicMock()


@pytest.fixture
def processor(mock_loader, mock_dlq):
    return EventProcessor(loader=mock_loader, dlq=mock_dlq)


# --------------------------------------------------------------------------- #
#  add_event() — добавление и дедупликация                                     #
# --------------------------------------------------------------------------- #


class TestAddEvent:
    def test_single_event_added(self, processor):
        event = _make_validated_event()
        processor.add_event(event)
        assert processor.buffer_size == 1

    def test_dedup_keeps_later_occurred_at(self, processor):
        """Две записи с одинаковым event_id — оставляет более позднее."""
        event1 = _make_validated_event(
            event_id='dup-1',
            occurred_at='2025-01-15T10:00:00+00:00',
        )
        event2 = _make_validated_event(
            event_id='dup-1',
            occurred_at='2025-01-15T11:00:00+00:00',
        )
        processor.add_event(event1)
        processor.add_event(event2)
        assert processor.buffer_size == 1
        stored = list(processor._buffer.values())[0]
        assert stored['occurred_at'] == '2025-01-15T11:00:00+00:00'

    def test_dedup_keeps_earlier_when_new_is_older(self, processor):
        """Новая запись с более ранним occurred_at не заменяет старую."""
        event1 = _make_validated_event(
            event_id='dup-2',
            occurred_at='2025-01-15T11:00:00+00:00',
        )
        event2 = _make_validated_event(
            event_id='dup-2',
            occurred_at='2025-01-15T10:00:00+00:00',
        )
        processor.add_event(event1)
        processor.add_event(event2)
        assert processor.buffer_size == 1
        stored = list(processor._buffer.values())[0]
        assert stored['occurred_at'] == '2025-01-15T11:00:00+00:00'

    def test_different_event_ids_accumulate(self, processor):
        processor.add_event(_make_validated_event(event_id='e1'))
        processor.add_event(_make_validated_event(event_id='e2'))
        processor.add_event(_make_validated_event(event_id='e3'))
        assert processor.buffer_size == 3

    def test_add_event_same_occurred_at_keeps_new(self, processor):
        """Равные occurred_at — новая запись заменяет."""
        ts = '2025-01-15T10:00:00+00:00'
        processor.add_event(_make_validated_event(event_id='e1', occurred_at=ts))
        processor.add_event(_make_validated_event(event_id='e1', occurred_at=ts, user_id='new_user'))
        assert processor.buffer_size == 1
        stored = list(processor._buffer.values())[0]
        assert stored['user_id'] == 'new_user'


# --------------------------------------------------------------------------- #
#  buffer_size property                                                        #
# --------------------------------------------------------------------------- #


class TestBufferSize:
    def test_empty_buffer(self, processor):
        assert processor.buffer_size == 0

    def test_after_add(self, processor):
        processor.add_event(_make_validated_event())
        assert processor.buffer_size == 1


# --------------------------------------------------------------------------- #
#  flush() — вставка в таблицы                                                 #
# --------------------------------------------------------------------------- #


class TestFlush:
    def test_empty_buffer_returns_zero(self, processor):
        result = processor.flush()
        count, success = result
        assert count == 0
        assert success is True
        processor._loader.bulk_insert.assert_not_called()

    def test_flush_calls_bulk_insert_for_events(self, processor):
        processor.add_event(_make_validated_event())
        processor.flush()
        processor._loader.bulk_insert.assert_called()

    def test_flush_calls_bulk_insert_movies_metrics(self, processor):
        event = _make_validated_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'quality_change',
                'content_id': 'c1',
            },
        )
        processor.add_event(event)
        processor.flush()
        processor._loader.bulk_insert_movies_metrics.assert_called()

    def test_flush_calls_bulk_insert_watch_sessions(self, processor):
        event = _make_validated_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'watch_complete',
                'content_id': 'c1',
                'watch_session_id': 'ws-1',
            },
        )
        processor.add_event(event)
        processor.flush()
        processor._loader.bulk_insert_watch_sessions.assert_called()

    def test_flush_calls_bulk_insert_events_always(self, processor):
        processor.add_event(_make_validated_event())
        processor.flush()
        calls = [c for c in processor._loader.mock_calls if 'bulk_insert' in str(c)]
        assert any('events' in str(c) for c in calls)

    def test_flush_returns_processed_count(self, processor):
        processor.add_event(_make_validated_event())
        count, success = processor.flush()
        assert isinstance(count, int)
        assert count >= 1  # хотя бы events row
        assert success is True

    def test_flush_clears_buffer(self, processor):
        processor.add_event(_make_validated_event())
        processor.flush()
        assert processor.buffer_size == 0

    def test_flush_multiple_events(self, processor):
        processor.add_event(_make_validated_event(event_id='e1'))
        processor.add_event(_make_validated_event(event_id='e2'))
        count, success = processor.flush()
        assert count >= 2  # 2 events rows минимум
        assert success is True

    def test_flush_after_dedup(self, processor):
        processor.add_event(_make_validated_event(event_id='dup', occurred_at='2025-01-01T00:00:00+00:00'))
        processor.add_event(_make_validated_event(event_id='dup', occurred_at='2025-12-31T23:59:59+00:00'))
        assert processor.buffer_size == 1
        count, success = processor.flush()
        assert count >= 1
        assert success is True


# --------------------------------------------------------------------------- #
#  _try_insert() — маршрутизация в DLQ при ошибке                             #
# --------------------------------------------------------------------------- #


class TestTryInsert:
    def test_failed_insert_routes_to_dlq(self, processor, mock_dlq):
        """При исключении в bulk_insert строки направляются в DLQ."""
        processor._loader.bulk_insert.side_effect = RuntimeError('connection lost')
        processor.add_event(_make_validated_event())
        processor.flush()
        # Должна быть запись в DLQ для failed insert
        assert mock_dlq.write.call_count >= 1
        call_kwargs = mock_dlq.write.call_args
        assert call_kwargs[1]['error_type'] == 'INSERT_ERROR'

    def test_successful_insert_no_dlq(self, processor, mock_dlq):
        processor._loader.bulk_insert.return_value = True
        processor.add_event(_make_validated_event())
        processor.flush()
        # При успешной вставке DLQ не вызывается
        assert mock_dlq.write.call_count == 0

    def test_exception_in_insert_routes_to_dlq(self, processor, mock_dlq):
        """_try_insert при исключении возвращает False и направляет строки в DLQ —
        исправленное поведение (был мёртвый код).
        """
        processor._loader.bulk_insert.side_effect = RuntimeError('connection lost')
        processor.add_event(_make_validated_event())
        processor.flush()
        # Исключение ловится, возвращается False, строки направляются в DLQ
        assert mock_dlq.write.call_count >= 1
        call_kwargs = mock_dlq.write.call_args
        assert call_kwargs[1]['error_type'] == 'INSERT_ERROR'


# --------------------------------------------------------------------------- #
#  Flush with transform errors                                                 #
# --------------------------------------------------------------------------- #


class TestFlushTransformError:
    def test_transform_error_routes_to_dlq(self, processor, mock_dlq):
        """Событие с sequence_number=None вызывает TypeError в
        transform_for_events → маршрутизация в DLQ."""
        event = {
            'event_id': 'bad-evt',
            'event_type': 'click',
            'schema_version': 1,
            'occurred_at': '2025-01-15T10:00:00+00:00',
            'received_at': '2025-01-15T10:00:01+00:00',
            'user_id': 'user-1',
            'session_id': 's1',
            'sequence_number': None,  # int(None) → TypeError
            'consent': True,
        }
        processor.add_event(event)
        processor.flush()
        # DLQ должен быть вызван
        assert mock_dlq.write.call_count >= 1
        call_kwargs = mock_dlq.write.call_args
        assert call_kwargs[1]['error_type'] == 'TRANSFORM_ERROR'
