"""Unit-tests для analytics_etl.transformer — преобразование событий в строки ClickHouse."""

import pytest
from datetime import datetime, timezone

from transformer import (
    transform_for_events,
    extract_content_id,
    transform_for_movies_metrics,
    transform_for_watch_sessions,
    _format_timestamp,
    _nullable,
    _empty_str,
    _safe_float,
)

# --------------------------------------------------------------------------- #
#  Фикстуры / helpers                                                          #
# --------------------------------------------------------------------------- #

BASE_EVENT = {
    'event_id': 'evt-001',
    'event_type': 'click',
    'schema_version': 1,
    'occurred_at': '2025-01-15T10:00:00+00:00',
    'received_at': '2025-01-15T10:00:01+00:00',
    'user_id': 'user-42',
    'anonymous_id': None,
    'session_id': 'sess-abc',
    'sequence_number': 10,
    'consent': True,
    'context': {
        'page_type': 'movie_card',
        'page_id': 'p1',
        'device': 'desktop',
        'browser': 'chrome',
        'app_version': '1.0',
    },
    'source': 'web',
    'payload': {
        'element_id': 'play-btn',
        'custom_event_type': None,
        'content_id': 'content-1',
        'watch_session_id': None,
        'duration_ms': None,
        'progress_percent': None,
        'from_quality': None,
        'to_quality': None,
        'tab_active': None,
    },
}


def _make_event(**overrides) -> dict:
    """Собрать событие с заменами."""
    event = dict(BASE_EVENT)
    event.update(overrides)
    return event


# --------------------------------------------------------------------------- #
#  transform_for_events                                                        #
# --------------------------------------------------------------------------- #


class TestTransformForEvents:
    def test_all_fields_mapped(self):
        result = transform_for_events(BASE_EVENT)
        assert result['event_id'] == 'evt-001'
        assert result['event_type'] == 'click'
        assert result['schema_version'] == 1
        assert result['user_id'] == 'user-42'
        assert result['anonymous_id'] is None
        assert result['session_id'] == 'sess-abc'
        assert result['sequence_number'] == 10
        assert result['consent'] == 1
        assert result['context_page_type'] == 'movie_card'
        assert result['source'] == 'web'
        assert result['payload_content_id'] == 'content-1'
        assert 'raw_event' in result

    def test_consent_false(self):
        event = _make_event(consent=False)
        result = transform_for_events(event)
        assert result['consent'] == 0

    def test_missing_context_fallback(self):
        event = _make_event(context=None)
        result = transform_for_events(event)
        assert result['context_page_type'] == ''
        assert result['context_page_id'] == ''

    def test_missing_payload_fallback(self):
        event = _make_event(payload=None)
        result = transform_for_events(event)
        assert result['payload_content_id'] is None
        assert result['custom_event_type'] is None

    def test_context_as_non_dict(self):
        """Context не dict — должен fallback на пустой dict."""
        event = _make_event(context='string_context')
        result = transform_for_events(event)
        assert result['context_page_type'] == ''

    def test_payload_as_non_dict(self):
        """Payload не dict — должен fallback на пустой dict."""
        event = _make_event(payload=42)
        result = transform_for_events(event)
        assert result['payload_content_id'] is None

    def test_timestamps_formatted(self):
        result = transform_for_events(BASE_EVENT)
        # DateTime64(3) format: YYYY-MM-DD HH:MM:SS.mmm
        assert len(result['occurred_at']) > 19  # с миллисекундами
        assert ' ' in result['occurred_at']

    def test_raw_event_is_json(self):
        import json
        result = transform_for_events(BASE_EVENT)
        parsed = json.loads(result['raw_event'])
        assert parsed['event_id'] == 'evt-001'


# --------------------------------------------------------------------------- #
#  extract_content_id                                                          #
# --------------------------------------------------------------------------- #


class TestExtractContentId:
    def test_from_payload_content_id(self):
        event = _make_event(payload={'content_id': 'c-42'})
        assert extract_content_id(event) == 'c-42'

    def test_from_payload_attrs_content_id(self):
        event = _make_event(payload={
            'attrs': {'content_id': 'c-42'},
        })
        assert extract_content_id(event) == 'c-42'

    def test_payload_content_id_takes_priority(self):
        event = _make_event(payload={
            'content_id': 'direct',
            'attrs': {'content_id': 'attr'},
        })
        assert extract_content_id(event) == 'direct'

    def test_returns_none_when_absent(self):
        event = _make_event(payload={})
        assert extract_content_id(event) is None

    def test_returns_none_when_payload_not_dict(self):
        event = _make_event(payload='not_dict')
        assert extract_content_id(event) is None

    def test_returns_none_when_no_payload(self):
        event = _make_event(payload=None)
        assert extract_content_id(event) is None


# --------------------------------------------------------------------------- #
#  transform_for_movies_metrics                                                #
# --------------------------------------------------------------------------- #


class TestTransformForMoviesMetrics:
    def test_quality_change_returns_row(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'quality_change',
                'content_id': 'c1',
            },
        )
        result = transform_for_movies_metrics(event)
        assert result is not None
        assert result['content_id'] == 'c1'
        assert result['is_quality_change'] == 1
        assert result['is_watch_complete'] == 0

    def test_watch_complete_returns_row(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'watch_complete',
                'content_id': 'c1',
            },
        )
        result = transform_for_movies_metrics(event)
        assert result is not None
        assert result['is_watch_complete'] == 1

    def test_click_event_returns_none(self):
        event = _make_event(event_type='click')
        assert transform_for_movies_metrics(event) is None

    def test_search_filter_returns_none(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'search_filter',
                'content_id': 'c1',
            },
        )
        assert transform_for_movies_metrics(event) is None

    def test_no_content_id_returns_none(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'quality_change',
                'content_id': None,
            },
        )
        assert transform_for_movies_metrics(event) is None

    def test_user_id_nullable(self):
        event = _make_event(
            event_type='custom_event',
            payload={'custom_event_type': 'quality_change', 'content_id': 'c1'},
            user_id=None,
        )
        result = transform_for_movies_metrics(event)
        assert result['user_id'] is None


# --------------------------------------------------------------------------- #
#  transform_for_watch_sessions                                                #
# --------------------------------------------------------------------------- #


class TestTransformForWatchSessions:
    def test_quality_change_with_session_returns_row(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'quality_change',
                'content_id': 'c1',
                'watch_session_id': 'ws-1',
                'to_quality': '1080p',
            },
        )
        result = transform_for_watch_sessions(event)
        assert result is not None
        assert result['watch_session_id'] == 'ws-1'
        assert result['quality'] == '1080p'

    def test_watch_complete_with_session_returns_row(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'watch_complete',
                'content_id': 'c1',
                'watch_session_id': 'ws-1',
                'progress_percent': 100.0,
            },
        )
        result = transform_for_watch_sessions(event)
        assert result is not None
        assert result['progress_percent'] == 100.0

    def test_click_event_returns_none(self):
        event = _make_event(event_type='click')
        assert transform_for_watch_sessions(event) is None

    def test_no_watch_session_id_returns_none(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'quality_change',
                'content_id': 'c1',
            },
        )
        assert transform_for_watch_sessions(event) is None

    def test_search_filter_returns_none(self):
        event = _make_event(
            event_type='custom_event',
            payload={
                'custom_event_type': 'search_filter',
                'filter_type': 'genre',
                'filter_value': 'comedy',
            },
        )
        assert transform_for_watch_sessions(event) is None


# --------------------------------------------------------------------------- #
#  _format_timestamp                                                           #
# --------------------------------------------------------------------------- #


class TestFormatTimestamp:
    def test_iso_string(self):
        result = _format_timestamp('2025-01-15T10:00:00+00:00')
        assert result == '2025-01-15 10:00:00.000'

    def test_datetime_object(self):
        dt = datetime(2025, 1, 15, 10, 0, 0, 123000, tzinfo=timezone.utc)
        result = _format_timestamp(dt)
        assert result == '2025-01-15 10:00:00.123'

    def test_datetime_without_tz(self):
        dt = datetime(2025, 1, 15, 10, 0, 0)
        result = _format_timestamp(dt)
        assert result == '2025-01-15 10:00:00.000'

    def test_string_already_formatted(self):
        result = _format_timestamp('2025-01-15 10:00:00.000')
        assert result == '2025-01-15 10:00:00.000'

    def test_unparseable_returns_str(self):
        result = _format_timestamp('invalid')
        assert result == 'invalid'

    def test_none_returns_str(self):
        result = _format_timestamp(None)
        assert result == 'None'


# --------------------------------------------------------------------------- #
#  Helper functions                                                            #
# --------------------------------------------------------------------------- #


class TestNullable:
    def test_none_returns_none(self):
        assert _nullable(None) is None

    def test_string(self):
        assert _nullable('hello') == 'hello'

    def test_int(self):
        assert _nullable(42) == '42'


class TestEmptyStr:
    def test_none_returns_empty(self):
        assert _empty_str(None) == ''

    def test_string(self):
        assert _empty_str('hello') == 'hello'

    def test_int(self):
        assert _empty_str(42) == '42'


class TestSafeFloat:
    def test_valid_float(self):
        assert _safe_float(3.14) == 3.14

    def test_valid_int(self):
        assert _safe_float(42) == 42.0

    def test_none_returns_zero(self):
        assert _safe_float(None) == 0.0

    def test_invalid_string_returns_zero(self):
        assert _safe_float('not_a_number') == 0.0

    def test_string_number(self):
        assert _safe_float('3.14') == 3.14
