"""Валидация событий пользователя с использованием Pydantic.

Модели соответствуют контракту в docs/user_events_contract.md.
Возвращает валидированный и нормализованный словарь события или ``None``,
если событие недопустимо — в этом случае его следует направить в DLQ.
"""

import logging
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Payload-модели по типам событий                                                #
# --------------------------------------------------------------------------- #


class ClickPayload(BaseModel):
    """payload для событий типа ``click``."""
    element_id: str
    element_type: str
    zone: str = ''
    attrs: dict[str, Any] = Field(default_factory=dict)


class PageViewPayload(BaseModel):
    """payload для событий ``page_view_start`` и ``page_view_end``."""
    page_view_id: str
    page_type: str
    page_id: Optional[str] = None
    duration_ms: Optional[int] = None
    tab_active: Optional[bool] = None


class QualityChangePayload(BaseModel):
    """payload для ``custom_event_type: quality_change``."""
    custom_event_type: Literal['quality_change']
    content_id: str
    watch_session_id: Optional[str] = None
    from_quality: Optional[str] = None
    to_quality: Optional[str] = None


class WatchCompletePayload(BaseModel):
    """payload для ``custom_event_type: watch_complete``."""
    custom_event_type: Literal['watch_complete']
    content_id: str
    progress_percent: Optional[float] = None


class SearchFilterPayload(BaseModel):
    """payload для ``custom_event_type: search_filter``."""
    custom_event_type: Literal['search_filter']
    filter_type: str
    filter_value: str
    search_session_id: Optional[str] = None
    result_count: Optional[int] = None


# Union-тип для payload кастомных событий
CustomEventPayload = Union[QualityChangePayload, WatchCompletePayload, SearchFilterPayload]


# --------------------------------------------------------------------------- #
#  Основной контекст и источник                                                   #
# --------------------------------------------------------------------------- #


class Context(BaseModel):
    """Контекст события: страница, устройство, браузер, версия."""
    page_type: Optional[str] = None
    page_id: Optional[str] = None
    device: Optional[str] = None
    browser: Optional[str] = None
    app_version: Optional[str] = None


SourceType = Union[Literal['web'], Literal['mobile'], Literal['ios'], Literal['android'], Literal['tv']]


# --------------------------------------------------------------------------- #
#  Основная модель события                                                          #
# --------------------------------------------------------------------------- #


class UserEvent(BaseModel):
    """Валидированное событие пользователя по контракту.

    Поля ``context``, ``payload`` могут быть отсутствовать — Pydantic
    заполнит их значениями по умолчанию (``None``), а валидаторы
    проверят обязательность идентификации пользователя.
    """

    event_id: str
    event_type: Literal['click', 'page_view_start', 'page_view_end', 'custom_event']
    schema_version: int = Field(gt=0)
    occurred_at: str
    received_at: str
    user_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    session_id: str
    sequence_number: int = Field(ge=0)
    consent: bool
    context: Optional[Context] = None
    source: Optional[SourceType] = None
    payload: Optional[dict[str, Any]] = None

    # --------------- валидаторы ----------------- #

    @field_validator('schema_version', mode='before')
    @classmethod
    def _strict_schema_version(cls, v: Any) -> int:
        """schema_version должен быть int, не строка."""
        if isinstance(v, str):
            raise ValueError('schema_version должен быть int, не строка')
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError('schema_version должен быть целым числом')
        return v

    @field_validator('occurred_at', 'received_at', mode='before')
    @classmethod
    def _strict_timestamp(cls, v: Any) -> str:
        """timestamps должны быть строками ISO format."""
        if not isinstance(v, str):
            raise ValueError('occurred_at/received_at должны быть строками')
        # Проверить, что строка-parseable
        from datetime import datetime
        try:
            ts = v
            if ts.endswith('Z'):
                ts = ts[:-1] + '+00:00'
            datetime.fromisoformat(ts)
        except (ValueError, TypeError) as e:
            raise ValueError(f'Недопустимый формат timestamp: {v!r}') from e
        return v

    @field_validator('consent', mode='before')
    @classmethod
    def _normalize_consent(cls, v: Any) -> bool:
        """Привести 0 / 1 к bool."""
        if isinstance(v, bool):
            return v
        if v in (0, 1):
            return bool(v)
        raise ValueError('consent должен быть True, False, 0 или 1')

    @field_validator('session_id')
    @classmethod
    def _non_empty_session_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('session_id не должна быть пустой')
        return v

    @model_validator(mode='after')
    def _validate_user_identification(self) -> 'UserEvent':
        """Хотя бы одно из user_id / anonymous_id обязательно."""
        if not self.user_id and not self.anonymous_id:
            raise ValueError(
                'Должно быть указано хотя бы одно из: user_id или anonymous_id'
            )
        return self

    @model_validator(mode='after')
    def _validate_payload_for_custom_event(self) -> 'UserEvent':
        """Для custom_event проверить custom_event_type в payload."""
        if self.event_type == 'custom_event':
            payload = self.payload or {}
            custom_type = payload.get('custom_event_type')
            valid_types = {'quality_change', 'watch_complete', 'search_filter'}
            if custom_type not in valid_types:
                raise ValueError(
                    f'Недопустимый custom_event_type: {custom_type!r}. '
                    f'Ожидалось одно из: {valid_types}'
                )
        return self


# --------------------------------------------------------------------------- #
#  Публичный API                                                                    #
# --------------------------------------------------------------------------- #


def validate_event(raw: dict) -> Optional[dict]:
    """Проверить сырое событие на соответствие контракту.

    Возвращает валидированный и нормализованный словарь (с ``consent`` типа
    ``bool``) или ``None``, если событие не проходит валидацию — такое событие
    следует направить в DLQ.

    Вызывает ``ValueError`` для неисправимых структурных ошибок (например, raw
    не является словарём).
    """
    if not isinstance(raw, dict):
        raise ValueError('Тело события не является словарём (not a dictionary)')

    try:
        validated = UserEvent.model_validate(raw)
    except Exception:
        logger.warning('Проверка события не пройдена')
        return None

    # Вернуть OrderedDict как обычный dict (Pydantic уже нормализовал consent)
    return validated.model_dump(exclude_unset=False)
