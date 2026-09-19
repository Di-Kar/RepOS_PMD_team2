"""Точка входа воркера-отправителя email (S10_T3, issue #96): читает
notifications.ready.v1, фильтрует channel="email", идемпотентно отправляет
письмо через SMTP. Запуск: `python -m src.main_send_email` (см.
docker-compose.yml, сервис notification_worker_email_sender). Терминальная
стадия пайплайна — Kafka-продюсера не запускает."""

import asyncio
import logging
import signal

import sentry_sdk

from src.clients.email_client import close_smtp_pool, init_smtp_pool
from src.consumer import run_consumer_loop
from src.core.config import settings
from src.core.tracer import configure_tracer
from src.db.postgres import close_pool, init_pool
from src.services.send_service import handle_message

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("notification_worker.email_sender")


async def main() -> None:
    configure_tracer("notification_worker_email_sender", debug=settings.debug)
    await init_pool()
    await init_smtp_pool()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    consumer_task = asyncio.create_task(
        run_consumer_loop(
            topic=settings.kafka_topic_ready,
            group_id=settings.kafka_consumer_group_send,
            handler=handle_message,
            stage="send",
        )
    )

    await stop_event.wait()
    logger.info("Shutdown signal received, stopping email sender worker")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await close_smtp_pool()
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
