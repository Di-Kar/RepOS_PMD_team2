"""Преобразование проверенных событий в строки для ClickHouse."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

EVENTS_TABLE = 'events'
MOVIES_METRICS_TABLE = 'movies_metrics'
WATCH_SESSIONS_TABLE = 'watch_sessions'


def transform_for_events(event: dict) -> dict:
    """Преобразовать проверенное событие в строку для таблицы ``events``.

    Возвращает плоский словарь, подходящий для пакетной вставки в ClickHouse.
    """
    raw_json = json.dumps(event, ensure_ascii=False)

    payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
    context = event.get('context') if isinstance(event.get('context'), dict) else {}

    return {
        'event_id': str(event['event_id']),
        'event_type': event['event_type'],
        'schema_version': int(event['schema_version']),
        'occurred_at': _format_timestamp(event['occurred_at']),
        'received_at': _format_timestamp(event['received_at']),
        'user_id': _nullable(event.get('user_id')),
        'anonymous_id': _nullable(event.get('anonymous_id')),
        'session_id': str(event['session_id']),
        'sequence_number': int(event['sequence_number']),
        'consent': 1 if event['consent'] else 0,
        'context_page_type': _empty_str(context.get('page_type')),
        'context_page_id': _empty_str(context.get('page_id')),
        'context_device': _empty_str(context.get('device')),
        'context_browser': _empty_str(context.get('browser')),
        'context_app_version': _empty_str(context.get('app_version')),
        'source': _empty_str(event.get('source')),
        'custom_event_type': payload.get('custom_event_type'),
        'payload_content_id': payload.get('content_id'),
        'payload_watch_session_id': payload.get('watch_session_id'),
        'payload_duration_ms': payload.get('duration_ms'),
        'payload_progress_percent': payload.get('progress_percent'),
        'payload_from_quality': payload.get('from_quality'),
        'payload_to_quality': payload.get('to_quality'),
        'payload_tab_active': payload.get('tab_active'),
        'raw_event': raw_json,
    }


def extract_content_id(event: dict) -> Optional[str]:
    """Извлечь content_id из проверенного события.

    Сначала ищет в payload.content_id, затем переходит к payload.attrs.content_id.
    """
    payload = event.get('payload')
    if not isinstance(payload, dict):
        return None

    content_id = payload.get('content_id')
    if content_id:
        return str(content_id)

    # Перейти к attrs.content_id (например, для событий клика)
    attrs = payload.get('attrs')
    if isinstance(attrs, dict):
        content_id = attrs.get('content_id')
        if content_id:
            return str(content_id)

    return None


def transform_for_movies_metrics(event: dict) -> Optional[dict]:
    """Создать агрегированную строку для таблицы ``movies_metrics``.

    Строки метрик создают только события, связанные с просмотром:
    - ``quality_change`` и ``watch_complete`` обновляют метрики.

    Возвращает None, если событие не относится к метрикам фильмов.
    """
    event_type = event.get('event_type')
    payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}

    if event_type != 'custom_event':
        return None

    custom_event_type = payload.get('custom_event_type')
    if custom_event_type not in ('quality_change', 'watch_complete'):
        return None

    content_id = payload.get('content_id') or (
        payload.get('attrs', {}).get('content_id') if isinstance(payload.get('attrs'), dict) else None
    )
    if not content_id:
        return None

    user_id = event.get('user_id')

    return {
        'content_id': str(content_id),
        'user_id': _nullable(user_id),
        'is_quality_change': 1 if custom_event_type == 'quality_change' else 0,
        'is_watch_complete': 1 if custom_event_type == 'watch_complete' else 0,
        'occurred_at': _format_timestamp(event['occurred_at']),
    }


def transform_for_watch_sessions(event: dict) -> Optional[dict]:
    """Создать строку сеанса просмотра для таблицы ``watch_sessions``.

    Создаёт строку для событий, которые ссылаются на watch_session_id:
    - quality_change
    - watch_complete
    """
    event_type = event.get('event_type')
    payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}

    if event_type != 'custom_event':
        return None

    custom_event_type = payload.get('custom_event_type')
    if custom_event_type not in ('quality_change', 'watch_complete'):
        return None

    watch_session_id = payload.get('watch_session_id')
    if not watch_session_id:
        return None

    content_id = payload.get('content_id')
    user_id = event.get('user_id')

    return {
        'watch_session_id': str(watch_session_id),
        'content_id': str(content_id) if content_id else '',
        'user_id': _nullable(user_id),
        'session_id': str(event.get('session_id', '')),
        'started_at': _format_timestamp(event['occurred_at']),
        'last_updated_at': _format_timestamp(event['received_at']),
        'quality': payload.get('to_quality', payload.get('from_quality', '')),
        'progress_percent': _safe_float(payload.get('progress_percent')),
        'duration_total': payload.get('duration_total_ms', 0),
    }


# ------------------------------------------------------------------ #
#  Вспомогательные функции                                                 #
# ------------------------------------------------------------------ #

def _parse_timestamp(ts) -> Optional[datetime]:
    """Разобрать строку в datetime (ISO формат или timestamp)."""
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _format_timestamp(ts) -> str:
    """Форматировать метку времени в DateTime64(3), совместимый с ClickHouse."""
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    if isinstance(ts, str):
        # Попытаться разобрать ISO формат
        parsed = _parse_timestamp(ts)
        if parsed:
            return parsed.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        # Резервный вариант: передать как есть
        return ts
    return str(ts)


def _nullable(value: Any) -> Optional[str]:
    """Вернуть значение в виде строки или None."""
    if value is None:
        return None
    return str(value)



def _empty_str(value: Any) -> str:
    """Вернуть пустую строку, если value is None, иначе str(value)."""
    if value is None:
        return ""
    return str(value)

def _safe_float(value: Any) -> float:
    """Безопасно преобразовать в float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0
