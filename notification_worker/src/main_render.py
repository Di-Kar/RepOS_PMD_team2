"""Точка входа воркера-рендерера (S10_T3, issue #96): читает
notifications.requests.v1, обогащает профилем из auth_service, рендерит
шаблон, публикует в notifications.ready.v1. Запуск: `python -m src.main_render`
(см. docker-compose.yml, сервис notification_worker_render)."""

import asyncio
import logging
import signal

import sentry_sdk

from src.consumer import run_consumer_loop
from src.core.config import settings
from src.core.tracer import configure_tracer
from src.db.postgres import close_pool, init_pool
from src.kafka_producer import close_producer, init_producer
from src.services.render_service import handle_message

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.01)

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("notification_worker.render")


async def main() -> None:
    configure_tracer("notification_worker_render", debug=settings.debug)
    await init_pool()
    await init_producer()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    consumer_task = asyncio.create_task(
        run_consumer_loop(
            topic=settings.kafka_topic_requests,
            group_id=settings.kafka_consumer_group_render,
            handler=handle_message,
        )
    )

    await stop_event.wait()
    logger.info("Shutdown signal received, stopping render worker")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await close_producer()
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
