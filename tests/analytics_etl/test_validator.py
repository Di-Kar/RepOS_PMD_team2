"""Unit-tests для analytics_etl.validator — обёртки над общим event_schemas.

Валидация самих схем (payload по типам, обязательность полей и т.п.)
покрыта в tests/shared/test_event_schemas.py — здесь только поведение
validate_event(): dict-in/dict-out на успехе, None на невалидном событии,
ValueError на структурно неисправимый ввод.
"""

import pytest

from validator import validate_event

EVENT_ID = 'b3f1c2a4-9e3a-4b7a-8b1a-7e2d3f4a5b6c'
SESSION_ID = '8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a'

VALID_EVENT = {
    'event_id': EVENT_ID,
    'event_type': 'click',
    'schema_version': 1,
    'occurred_at': '2025-01-15T10:00:00+00:00',
    'received_at': '2025-01-15T10:00:01+00:00',
    'user_id': 'user-42',
    'session_id': SESSION_ID,
    'sequence_number': 10,
    'consent': True,
    'context': {
        'page_type': 'movie_card',
        'device': 'desktop',
    },
    'source': 'web',
    'payload': {
        'element_id': 'play-btn',
        'element_type': 'button',
        'zone': 'hero',
        'attrs': {},
    },
}


def _make_event(**overrides) -> dict:
    event = dict(VALID_EVENT)
    event.update(overrides)
    return event


class TestValidateEvent:
    def test_valid_event_returns_dict(self):
        result = validate_event(_make_event())
        assert isinstance(result, dict)
        assert result['event_id'] == EVENT_ID
        assert result['consent'] is True

    def test_result_is_json_safe(self):
        """model_dump(mode='json') — иначе UUID/datetime ломают json.dumps в transformer.py."""
        result = validate_event(_make_event())
        assert isinstance(result['event_id'], str)
        assert isinstance(result['session_id'], str)
        assert isinstance(result['occurred_at'], str)

    def test_invalid_event_returns_none(self):
        # Отсутствует user_id/anonymous_id
        raw = _make_event(user_id=None, anonymous_id=None)
        assert validate_event(raw) is None

    def test_click_without_zone_returns_none(self):
        """zone обязателен по контракту — раньше ETL молча подставлял ''."""
        raw = _make_event(payload={'element_id': 'btn', 'element_type': 'button', 'attrs': {}})
        assert validate_event(raw) is None

    def test_custom_event_with_incomplete_payload_returns_none(self):
        """quality_change без watch_session_id/from_quality/to_quality — раньше проходило."""
        raw = _make_event(event_type='custom_event', payload={
            'custom_event_type': 'quality_change',
            'content_id': 'c1',
        })
        assert validate_event(raw) is None

    def test_custom_event_with_full_payload_returns_dict(self):
        raw = _make_event(event_type='custom_event', payload={
            'custom_event_type': 'quality_change',
            'content_id': 'c1',
            'watch_session_id': 'ws-1',
            'from_quality': '720p',
            'to_quality': '1080p',
        })
        result = validate_event(raw)
        assert result is not None
        assert result['event_type'] == 'custom_event'

    def test_non_dict_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event('not a dict')

    def test_none_input_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event(None)

    def test_list_input_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event([1, 2, 3])
