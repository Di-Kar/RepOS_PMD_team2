"""Unit-tests для analytics_etl.validator — Pydantic-модели и валидация событий."""

import pytest
from pydantic import ValidationError

from validator import (
    ClickPayload,
    Context,
    QualityChangePayload,
    SearchFilterPayload,
    UserEvent,
    WatchCompletePayload,
    validate_event,
    normalize_consent,
)

# --------------------------------------------------------------------------- #
#  Фикстуры / helpers                                                          #
# --------------------------------------------------------------------------- #

VALID_EVENT = {
    'event_id': 'evt-001',
    'event_type': 'click',
    'schema_version': 1,
    'occurred_at': '2025-01-15T10:00:00+00:00',
    'received_at': '2025-01-15T10:00:01+00:00',
    'user_id': 'user-42',
    'session_id': 'sess-abc',
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
    },
}


def _make_basic_event(**overrides) -> dict:
    """Собрать базовое валидное событие с заменами."""
    event = dict(VALID_EVENT)
    event.update(overrides)
    return event


# --------------------------------------------------------------------------- #
#  Payload-модели                                                              #
# --------------------------------------------------------------------------- #


class TestClickPayload:
    def test_valid(self):
        p = ClickPayload(element_id='btn-1', element_type='button')
        assert p.element_id == 'btn-1'

    def test_defaults(self):
        p = ClickPayload(element_id='btn-1', element_type='button')
        assert p.zone == ''
        assert p.attrs == {}


class TestPageViewPayload:
    def test_valid(self):
        from validator import PageViewPayload
        p = PageViewPayload(page_view_id='pv-1', page_type='home')
        assert p.page_view_id == 'pv-1'


class TestQualityChangePayload:
    def test_valid(self):
        p = QualityChangePayload(
            custom_event_type='quality_change',
            content_id='content-1',
        )
        assert p.custom_event_type == 'quality_change'

    def test_rejects_invalid_type(self):
        with pytest.raises(ValidationError):
            QualityChangePayload(
                custom_event_type='click',
                content_id='content-1',
            )


class TestWatchCompletePayload:
    def test_valid(self):
        p = WatchCompletePayload(
            custom_event_type='watch_complete',
            content_id='content-1',
        )
        assert p.progress_percent is None


class TestSearchFilterPayload:
    def test_valid(self):
        p = SearchFilterPayload(
            custom_event_type='search_filter',
            filter_type='genre',
            filter_value='comedy',
        )
        assert p.filter_type == 'genre'


class TestContext:
    def test_all_none(self):
        c = Context()
        assert c.page_type is None

    def test_partial(self):
        c = Context(page_type='home', device='mobile')
        assert c.device == 'mobile'
        assert c.browser is None


# --------------------------------------------------------------------------- #
#  UserEvent — валидные события                                                 #
# --------------------------------------------------------------------------- #


class TestUserEventValid:
    def test_minimal_valid(self):
        raw = _make_basic_event(event_type='custom_event', payload={
            'custom_event_type': 'quality_change',
            'content_id': 'c1',
        })
        evt = UserEvent.model_validate(raw)
        assert evt.event_id == 'evt-001'
        assert evt.consent is True

    def test_with_anonymous_id(self):
        raw = _make_basic_event(user_id=None, anonymous_id='anon-1')
        evt = UserEvent.model_validate(raw)
        assert evt.anonymous_id == 'anon-1'

    def test_consent_from_int(self):
        raw = _make_basic_event(consent=1)
        evt = UserEvent.model_validate(raw)
        assert evt.consent is True

    def test_schema_version_2(self):
        raw = _make_basic_event(schema_version=2)
        evt = UserEvent.model_validate(raw)
        assert evt.schema_version == 2


# --------------------------------------------------------------------------- #
#  UserEvent — ошибки валидации                                                 #
# --------------------------------------------------------------------------- #


class TestUserEventValidationErrors:
    def test_missing_user_and_anonymous(self):
        raw = _make_basic_event(user_id=None, anonymous_id=None)
        with pytest.raises(ValidationError) as exc_info:
            UserEvent.model_validate(raw)
        # Модель-валидатор требует хотя бы один ID
        errors = str(exc_info.value)
        assert 'user_id' in errors.lower() or 'anonymous_id' in errors.lower()

    def test_schema_version_string(self):
        raw = _make_basic_event(schema_version='1')
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_schema_version_boolean(self):
        raw = _make_basic_event(schema_version=True)
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_invalid_timestamp(self):
        raw = _make_basic_event(occurred_at='not-a-date')
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_empty_session_id(self):
        raw = _make_basic_event(session_id='')
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_invalid_consent_not_bool_or_01(self):
        raw = _make_basic_event(consent='yes')
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_invalid_custom_event_type(self):
        raw = _make_basic_event(event_type='custom_event', payload={
            'custom_event_type': 'invalid_type',
            'content_id': 'c1',
        })
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)


# --------------------------------------------------------------------------- #
#  normalize_consent                                                           #
# --------------------------------------------------------------------------- #


class TestNormalizeConsent:
    def test_zero_becomes_false(self):
        assert normalize_consent(0) is False

    def test_one_becomes_true(self):
        assert normalize_consent(1) is True

    def test_bool_passthrough_true(self):
        assert normalize_consent(True) is True

    def test_bool_passthrough_false(self):
        assert normalize_consent(False) is False


# --------------------------------------------------------------------------- #
#  validate_event()                                                            #
# --------------------------------------------------------------------------- #


class TestValidateEvent:
    def test_valid_event_returns_dict(self):
        result = validate_event(_make_basic_event())
        assert isinstance(result, dict)
        assert result['event_id'] == 'evt-001'
        assert result['consent'] is True

    def test_invalid_event_returns_none(self):
        # Отсутствует user_id/anonymous_id
        raw = _make_basic_event(user_id=None, anonymous_id=None)
        result = validate_event(raw)
        assert result is None

    def test_non_dict_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event('not a dict')

    def test_none_input_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event(None)

    def test_list_input_raises_value_error(self):
        with pytest.raises(ValueError, match='not a dictionary'):
            validate_event([1, 2, 3])

    def test_custom_event_with_quality_change(self):
        raw = _make_basic_event(event_type='custom_event', payload={
            'custom_event_type': 'quality_change',
            'content_id': 'c1',
        })
        result = validate_event(raw)
        assert result is not None
        assert result['event_type'] == 'custom_event'


# --------------------------------------------------------------------------- #
#  model_validator / field_validator                                           #
# --------------------------------------------------------------------------- #


class TestModelValidator:
    def test_custom_event_payload_validation(self):
        """model_validator для custom_event: payload должен иметь допустимый custom_event_type."""
        raw = _make_basic_event(event_type='custom_event', payload={
            'custom_event_type': 'watch_complete',
            'content_id': 'c1',
        })
        evt = UserEvent.model_validate(raw)
        assert evt.event_type == 'custom_event'

    def test_custom_event_without_valid_type(self):
        raw = _make_basic_event(event_type='custom_event', payload={
            'custom_event_type': 'bad_type',
        })
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_field_validator_strict_timestamp(self):
        """field_validator: occurred_at должен быть строкой ISO."""
        raw = _make_basic_event(occurred_at=12345)
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_field_validator_strict_schema_version(self):
        """field_validator: schema_version должен быть int, не строка."""
        raw = _make_basic_event(schema_version='1')
        with pytest.raises(ValidationError):
            UserEvent.model_validate(raw)

    def test_timestamp_with_z_suffix(self):
        """Timestamp с 'Z' суффиксом должен парситься."""
        raw = _make_basic_event(
            occurred_at='2025-01-15T10:00:00Z',
            received_at='2025-01-15T10:00:01Z',
        )
        evt = UserEvent.model_validate(raw)
        assert evt.occurred_at == '2025-01-15T10:00:00Z'
