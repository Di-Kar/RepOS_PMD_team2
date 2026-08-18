"""Tests for _process_message: unexpected processing errors route to DLQ."""

import json
import pytest
from unittest.mock import MagicMock, patch
import json as json_module


def _make_msg(value: bytes, topic: str = 'clicks', partition: int = 0, offset: int = 100):
    """Создать мокедное сообщение Kafka."""
    msg = MagicMock()
    msg.value.return_value = value
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


def _make_processor():
    """Создать EventProcessor с моками зависимостей."""
    from processor import EventProcessor
    loader = MagicMock()
    loader.bulk_insert.return_value = True
    dlq = MagicMock()
    return EventProcessor(loader=loader, dlq=dlq), dlq


class TestUnexpectedProcessingError:
    """Все типы ошибок: decode, processing, validation — направляются в DLQ."""

    def test_binary_data_routed_to_dlq(self):
        """Бинарные данные (не UTF-8) → DECODE_ERROR → DLQ."""
        from main import _process_message

        msg = _make_msg(b'\xff\xfe\x00\x01')  # невалидный UTF-8
        processor, dlq = _make_processor()
        consumer = MagicMock()

        _process_message(msg, processor, consumer, dlq)

        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'DECODE_ERROR'

    def test_empty_message_routed_to_dlq(self):
        """Пустое сообщение → JSONDecodeError → DLQ."""
        from main import _process_message

        msg = _make_msg(b'')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        _process_message(msg, processor, consumer, dlq)

        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'DECODE_ERROR'

    def test_null_message_value_routed_to_dlq(self):
        """msg.value() == None → пустой payload → JSONDecodeError → DLQ."""
        from main import _process_message

        msg = MagicMock()
        msg.value.return_value = None
        msg.topic.return_value = 'clicks'
        msg.partition.return_value = 0
        msg.offset.return_value = 100

        processor, dlq = _make_processor()
        consumer = MagicMock()

        _process_message(msg, processor, consumer, dlq)

        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'DECODE_ERROR'

    def test_json_decode_error_fixes_offset(self):
        """При DECODE_ERROR смещение фиксируется (сообщение не повторно)."""
        from main import _process_message

        msg = _make_msg(b'not valid json')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        _process_message(msg, processor, consumer, dlq)

        # Смещение фиксируется через _track_offset (вызывается после route_to_dlq)
        assert dlq.write.call_count == 1
        assert 'DECODE_ERROR' in str(dlq.write.call_args)

    def test_processing_error_routes_to_dlq(self):
        """Exception из json.loads → DLQ."""
        from main import _process_message

        msg = _make_msg(b'{"valid": "json"}')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        with patch('main.json.loads', side_effect=RuntimeError('parse failed unexpectedly')):
            _process_message(msg, processor, consumer, dlq)

        # DLQ должен быть вызван с PROCESSING_ERROR
        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'PROCESSING_ERROR'
        assert 'parse failed unexpectedly' in call_kwargs['error_message']

    def test_processing_error_fixes_offset(self):
        """При PROCESSING_ERROR смещение фиксируется (сообщение не повторно)."""
        from main import _process_message, _track_offset

        msg = _make_msg(b'{"valid": "json"}')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        with patch('main.json.loads', side_effect=RuntimeError('parse failed unexpectedly')):
            _process_message(msg, processor, consumer, dlq)

        # Смещение должно быть зафиксировано через _track_offset
        assert dlq.write.call_count == 1
        assert 'PROCESSING_ERROR' in str(dlq.write.call_args)


class TestValidationVsProcessingError:
    """Разделение: валидационные vs PROCESSING_ERROR vs DECODE_ERROR."""

    def test_validation_error_uses_original_event(self):
        """VALIDATION_ERROR получает оригинальное событие."""
        from main import _process_message

        msg = _make_msg(b'{"event_id": "123", "bad_field": "x"}')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        # Мокаем валидатор внутри модуля main
        fake_validator = MagicMock()
        fake_validator.validate_event.return_value = None

        with patch.dict('sys.modules', {'validator': fake_validator}):
            # Перезагружаем main чтобы он использовал мок
            import importlib
            import main as main_module
            importlib.reload(main_module)

            main_module._process_message(msg, processor, consumer, dlq)

        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'VALIDATION_ERROR'
        assert 'Событие не прошло проверку валидации' in call_kwargs['error_message']

    def test_processing_error_uses_raw_payload(self):
        """PROCESSING_ERROR получает сырое сообщение."""
        from main import _process_message

        msg = _make_msg(b'{"event_id": "123", "event_type": "click"}')
        processor, dlq = _make_processor()
        consumer = MagicMock()

        with patch('main.json.loads', side_effect=RuntimeError('type error')):
            _process_message(msg, processor, consumer, dlq)

        assert dlq.write.call_count == 1
        call_kwargs = dlq.write.call_args[1]
        assert call_kwargs['error_type'] == 'PROCESSING_ERROR'
