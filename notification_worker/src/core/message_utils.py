"""Общие утилиты разбора сырых Kafka-сообщений — использовались независимо
и почти идентично в render_service.py и send_service.py (дублирование,
найденное ревью); вынесены сюда, чтобы будущая правка логики усечения/
парсинга не расходилась между двумя стадиями."""

import uuid
from typing import Any, Optional


def safe_raw_message(raw_bytes: bytes) -> Optional[dict[str, Any]]:
    """Best-effort декодирование сырых байт сообщения для diagnostics в DLQ —
    используется, когда JSON/схема не распарсились и штатный
    `message.model_dump()` недоступен."""
    try:
        return {"raw_utf8": raw_bytes.decode("utf-8", errors="replace")[:4000]}
    except Exception:  # noqa: BLE001 — диагностический best-effort, не должен падать сам
        return None


def try_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
