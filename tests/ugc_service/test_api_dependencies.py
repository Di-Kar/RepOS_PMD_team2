"""Тесты для зависимостей API: валидация ObjectId."""

from api.dependencies import get_validated_object_id
from bson import ObjectId
from fastapi import HTTPException, status
from pytest import raises


class TestGetValidatedObjectId:
    """Тесты функции get_validated_object_id."""

    def test_valid_object_id_returns_object(self):
        """Валидный 24-символьный hex-строковый ObjectId возвращается без ошибок."""
        valid_hex = '550e8400e29b41d4a7164466'
        result = get_validated_object_id(valid_hex)
        assert isinstance(result, ObjectId)
        assert str(result) == valid_hex

    def test_valid_object_id_with_uppercase(self):
        """ObjectId может содержать буквы в верхнем регистре."""
        valid_hex = '550E8400E29B41D4A7164466'
        result = get_validated_object_id(valid_hex)
        assert isinstance(result, ObjectId)

    def test_too_short_id_raises_422(self):
        """Слишком короткая строка (меньше 24 символов) → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('550e8400e29b41d4')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_too_long_id_raises_422(self):
        """Слишком длинная строка (больше 24 символов) → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('550e8400e29b41d4a716446600000000')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_non_hex_characters_raise_422(self):
        """Строка с не-hex символами → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('not-an-id')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_empty_string_raises_422(self):
        """Пустая строка → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_special_characters_raise_422(self):
        """Спецсимволы → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('!!!invalid!!!')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_error_message_contains_original_id(self):
        """В сообщении об ошибке содержится исходный невалидный ID."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('not-an-id')
        assert 'not-an-id' in str(exc_info.value.detail)

    def test_random_string_raises_422(self):
        """Случайная строка → 422."""
        with raises(HTTPException) as exc_info:
            get_validated_object_id('abc123xyz789random')
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
