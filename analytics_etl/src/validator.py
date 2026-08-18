"""Валидация событий пользователя через общий пакет event_schemas.

Возвращает валидированный и нормализованный словарь события или ``None``,
если событие недопустимо — в этом случае его следует направить в DLQ.
"""

import logging
from typing import Optional

from event_schemas import UserEvent
from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

_event_adapter: TypeAdapter = TypeAdapter(UserEvent)


def validate_event(raw: dict) -> Optional[dict]:
    """Проверить сырое событие на соответствие контракту.

    Возвращает валидированный и нормализованный словарь (JSON-совместимые
    типы — как для сериализации в Kafka) или ``None``, если событие не
    проходит валидацию — такое событие следует направить в DLQ.

    Вызывает ``ValueError`` для неисправимых структурных ошибок (например, raw
    не является словарём).
    """
    if not isinstance(raw, dict):
        raise ValueError('Тело события не является словарём (not a dictionary)')

    try:
        validated = _event_adapter.validate_python(raw)
    except ValidationError:
        logger.warning('Проверка события не пройдена')
        return None

    return validated.model_dump(mode='json')
