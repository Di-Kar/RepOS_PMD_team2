"""Юнит-тесты инварианта consumer.py: offset подтверждается только после
того, как результат или причина сбоя надёжно сохранены (см. ревью S10_R4 —
раньше ошибка записи в DLQ глушилась, и сообщение коммитилось, исчезая и из
доставки, и из DLQ).

В отличие от остальных тестов воркера (чёрный ящик через docker-compose:
notification_api -> Kafka -> Postgres/MailHog) здесь нужна недоступная DLQ
при живой Kafka — такое состояние снаружи не воспроизвести, поэтому
consumer-loop вызывается напрямую с моками, по образцу
tests/analytics_etl/test_commit_offsets.py.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Исходники воркера смонтированы в контейнер тестов как /notification_worker
# (см. docker-compose.yml, сервис tests); локально — соседний каталог репо.
_WORKER_ROOT = Path(__file__).parent.parent.parent / "notification_worker"
if _WORKER_ROOT.is_dir() and str(_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKER_ROOT))

from aiokafka.structs import TopicPartition  # noqa: E402

from src import consumer as consumer_module  # noqa: E402
from src.core.errors import DlqUnavailableError  # noqa: E402

TP = TopicPartition("notifications.ready.v1", 0)
OFFSET = 42


@pytest.fixture
def record():
    """Минимальный ConsumerRecord — consumer.py читает только topic,
    partition, offset и value."""
    rec = MagicMock()
    rec.topic = TP.topic
    rec.partition = TP.partition
    rec.offset = OFFSET
    rec.value = b'{"request_id": "test"}'
    return rec


@pytest.fixture
def mock_consumer():
    kafka_consumer = MagicMock()
    kafka_consumer.commit = AsyncMock()
    return kafka_consumer


@pytest.fixture
def fast_settings(monkeypatch):
    """Ускоряем ретраи/паузы, чтобы тест шёл доли секунды."""
    settings = consumer_module.settings
    monkeypatch.setattr(settings, "retry_max_attempts", 1, raising=False)
    monkeypatch.setattr(settings, "retry_backoff_seconds", 0.0, raising=False)
    monkeypatch.setattr(settings, "partition_pause_seconds", 0.01, raising=False)
    monkeypatch.setattr(settings, "max_pause_cycles", 1, raising=False)
    monkeypatch.setattr(
        settings, "dlq_unavailable_max_hold_seconds", 0.05, raising=False
    )
    return settings


async def _run(mock_consumer, record, handler):
    await consumer_module._process_with_retry(
        mock_consumer, TP, record, handler, "send", consumer_module.uuid.uuid4()
    )


@pytest.mark.usefixtures("fast_settings")
async def test_dlq_unavailable_does_not_commit(mock_consumer, record):
    """DLQ недоступна -> сообщение НЕ подтверждается, партиция стоит на
    паузе, а по истечении удержания поднимается DlqUnavailableError."""

    async def handler(_record, _attempt_id):
        raise RuntimeError("postgres is down")

    with patch.object(consumer_module, "get_pool"), patch.object(
        consumer_module.queries,
        "insert_dlq",
        AsyncMock(side_effect=RuntimeError("postgres is down")),
    ):
        with pytest.raises(DlqUnavailableError):
            await _run(mock_consumer, record, handler)

    mock_consumer.commit.assert_not_called()
    mock_consumer.pause.assert_called_with(TP)
    # Партицию отпускаем в finally, чтобы не оставить её на паузе навсегда.
    mock_consumer.resume.assert_called_with(TP)


@pytest.mark.usefixtures("fast_settings")
async def test_commit_after_dlq_recovers(mock_consumer, record):
    """DLQ поднялась со второй попытки -> ровно один commit, и только
    после успешной записи причины сбоя."""

    async def handler(_record, _attempt_id):
        raise RuntimeError("smtp is down")

    insert_dlq = AsyncMock(side_effect=[RuntimeError("postgres is down"), None])
    with patch.object(consumer_module, "get_pool"), patch.object(
        consumer_module.queries, "insert_dlq", insert_dlq
    ):
        await _run(mock_consumer, record, handler)

    assert insert_dlq.await_count == 2
    mock_consumer.commit.assert_awaited_once_with({TP: OFFSET + 1})


@pytest.mark.usefixtures("fast_settings")
async def test_successful_handler_commits_without_pause(mock_consumer, record):
    """Регрессия happy-path: успешная обработка -> один commit, партиция не
    ставится на паузу."""
    handler = AsyncMock()

    await _run(mock_consumer, record, handler)

    handler.assert_awaited_once()
    mock_consumer.commit.assert_awaited_once_with({TP: OFFSET + 1})
    mock_consumer.pause.assert_not_called()


@pytest.mark.usefixtures("fast_settings")
async def test_handler_dlq_unavailable_propagates_without_commit(
    mock_consumer, record
):
    """DlqUnavailableError из самого обработчика (send_service не смог
    записать ручной разбор) пробрасывается сразу: offset не подтверждается,
    а handler не повторяется — повтор с тем же attempt_id задублировал бы
    письмо."""
    handler = AsyncMock(side_effect=DlqUnavailableError("cannot record outcome"))

    with pytest.raises(DlqUnavailableError):
        await _run(mock_consumer, record, handler)

    handler.assert_awaited_once()
    mock_consumer.commit.assert_not_called()


@pytest.mark.usefixtures("fast_settings")
async def test_shutdown_while_dlq_unavailable_resumes_partition(
    mock_consumer, record, monkeypatch
):
    """Отмена задачи (graceful shutdown) во время удержания партиции не
    оставляет её на паузе и не коммитит сообщение."""
    # Бюджет удержания заведомо больше теста — отмена гарантированно
    # приходит внутрь удержания, а не после того, как оно истекло. Паузу
    # (fast_settings) при этом оставляем короткой, иначе тест не успеет
    # дойти до самого удержания.
    monkeypatch.setattr(
        consumer_module.settings, "dlq_unavailable_max_hold_seconds", 30.0
    )

    async def handler(_record, _attempt_id):
        raise RuntimeError("postgres is down")

    holding = asyncio.Event()

    async def failing_insert_dlq(*_args, **_kwargs):
        # Первая же неудачная запись в DLQ = мы внутри удержания.
        holding.set()
        raise RuntimeError("postgres is down")

    with patch.object(consumer_module, "get_pool"), patch.object(
        consumer_module.queries, "insert_dlq", failing_insert_dlq
    ):
        task = asyncio.create_task(_run(mock_consumer, record, handler))
        await asyncio.wait_for(holding.wait(), timeout=5)
        # Отдаём управление, чтобы задача дошла до паузы и sleep.
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_consumer.commit.assert_not_called()
    mock_consumer.pause.assert_called_with(TP)
    mock_consumer.resume.assert_called_with(TP)
