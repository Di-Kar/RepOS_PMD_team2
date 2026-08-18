"""Unit-тесты для shared/event_schemas.py — общего контракта событий
(docs/user_events_contract.md), которым пользуются и event_api, и analytics_etl.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from event_schemas import (
    ClickPayload,
    PageViewEndPayload,
    PageViewStartPayload,
    QualityChangePayload,
    SearchFilterPayload,
    TOPIC_BY_EVENT_TYPE,
    UserEvent,
    WatchCompletePayload,
)

_event_adapter = TypeAdapter(UserEvent)

EVENT_ID = 'b3f1c2a4-9e3a-4b7a-8b1a-7e2d3f4a5b6c'
SESSION_ID = '8f6a1e2b-4c3d-4a2b-9f1e-2b3c4d5e6f7a'


def _base(**overrides) -> dict:
    event = {
        'event_id': EVENT_ID,
        'schema_version': 1,
        'occurred_at': '2026-08-09T12:34:56.789Z',
        'user_id': 'user-482910',
        'session_id': SESSION_ID,
        'sequence_number': 14,
        'consent': True,
        'context': {'page_type': 'movie_card'},
        'source': 'web',
    }
    event.update(overrides)
    return event


# --------------------------------------------------------------------------- #
#  Payload-модели по типам событий (раздел 3 контракта)                        #
# --------------------------------------------------------------------------- #


class TestClickPayload:
    def test_valid(self):
        p = ClickPayload(element_id='btn', element_type='button', zone='hero')
        assert p.zone == 'hero'
        assert p.attrs == {}

    def test_zone_required(self):
        with pytest.raises(ValidationError):
            ClickPayload(element_id='btn', element_type='button')

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            ClickPayload(element_id='btn', element_type='button', zone='hero', unexpected='x')


class TestPageViewPayloads:
    def test_start_minimal(self):
        p = PageViewStartPayload(page_view_id='pv-1', page_type='home')
        assert p.page_id is None

    def test_end_requires_duration_and_tab_active(self):
        with pytest.raises(ValidationError):
            PageViewEndPayload(page_view_id='pv-1', page_type='home')

    def test_end_valid(self):
        p = PageViewEndPayload(page_view_id='pv-1', page_type='home', duration_ms=1000, tab_active=True)
        assert p.duration_ms == 1000


class TestCustomEventPayloads:
    def test_quality_change_requires_all_fields(self):
        with pytest.raises(ValidationError):
            QualityChangePayload(custom_event_type='quality_change', content_id='c1')

    def test_quality_change_valid(self):
        p = QualityChangePayload(
            custom_event_type='quality_change',
            content_id='c1',
            watch_session_id='ws-1',
            from_quality='720p',
            to_quality='1080p',
        )
        assert p.to_quality == '1080p'

    def test_watch_complete_progress_out_of_range(self):
        with pytest.raises(ValidationError):
            WatchCompletePayload(custom_event_type='watch_complete', content_id='c1', progress_percent=101)

    def test_search_filter_optional_fields(self):
        p = SearchFilterPayload(custom_event_type='search_filter', filter_type='genre', filter_value='comedy')
        assert p.result_count is None


# --------------------------------------------------------------------------- #
#  UserEvent — дискриминируемый union и общие поля (раздел 2 контракта)        #
# --------------------------------------------------------------------------- #


class TestUserEventValid:
    def test_click_event(self):
        raw = _base(event_type='click', payload={
            'element_id': 'play-button', 'element_type': 'button', 'zone': 'hero',
        })
        evt = _event_adapter.validate_python(raw)
        assert str(evt.event_id) == EVENT_ID

    def test_custom_event_quality_change(self):
        raw = _base(event_type='custom_event', payload={
            'custom_event_type': 'quality_change', 'content_id': 'c1',
            'watch_session_id': 'ws-1', 'from_quality': '720p', 'to_quality': '1080p',
        })
        evt = _event_adapter.validate_python(raw)
        assert evt.payload.custom_event_type == 'quality_change'

    def test_anonymous_id_accepted_without_user_id(self):
        raw = _base(event_type='click', user_id=None, anonymous_id='anon-1', payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })
        evt = _event_adapter.validate_python(raw)
        assert evt.anonymous_id == 'anon-1'


class TestUserEventValidationErrors:
    def test_missing_identity(self):
        raw = _base(event_type='click', user_id=None, anonymous_id=None, payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(raw)

    def test_unknown_event_type_rejected(self):
        raw = _base(event_type='unknown', payload={})
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(raw)

    def test_payload_mismatched_with_event_type(self):
        """payload для click, но event_type page_view_start — discriminator должен отклонить."""
        raw = _base(event_type='page_view_start', payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(raw)

    def test_extra_top_level_field_forbidden(self):
        raw = _base(event_type='click', payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })
        raw['unexpected'] = 'x'
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(raw)

    def test_invalid_event_id_not_uuid(self):
        raw = _base(event_type='click', event_id='not-a-uuid', payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(raw)


class TestConsentNormalization:
    def _event(self, consent):
        return _base(event_type='click', consent=consent, payload={
            'element_id': 'btn', 'element_type': 'button', 'zone': 'hero',
        })

    def test_int_zero_becomes_false(self):
        evt = _event_adapter.validate_python(self._event(0))
        assert evt.consent is False

    def test_int_one_becomes_true(self):
        evt = _event_adapter.validate_python(self._event(1))
        assert evt.consent is True

    def test_arbitrary_string_rejected(self):
        with pytest.raises(ValidationError):
            _event_adapter.validate_python(self._event('yes'))


def test_topic_by_event_type_covers_all_event_types():
    for event_type in ('click', 'page_view_start', 'page_view_end', 'custom_event'):
        assert event_type in TOPIC_BY_EVENT_TYPE
