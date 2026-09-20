"""Точка входа воркера-рендерера (S10_T3, issue #96): читает
notifications.requests.v1, обогащает профилем из auth_service, рендерит
шаблон, публикует в notifications.ready.v1. Запуск: `python -m src.main_render`
(см. docker-compose.yml, сервис notification_worker_render)."""

import asyncio
import logging
import signal

import sentry_sdk

from src.clients.auth_client import close_auth_client, init_auth_client
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
    await init_auth_client()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    consumer_task = asyncio.create_task(
        run_consumer_loop(
            topic=settings.kafka_topic_requests,
            group_id=settings.kafka_consumer_group_render,
            handler=handle_message,
            stage="render",
        )
    )

    # Ждём и сигнал остановки, и сам consumer-loop: он может завершиться
    # ошибкой (например DlqUnavailableError — DLQ недоступна, offset не
    # подтверждён), и тогда процесс обязан упасть, а не остаться "живым",
    # ничего не читая, — docker перезапустит сервис (restart: unless-stopped)
    # и работа продолжится с неподтверждённого offset'а.
    stop_task = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {consumer_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )

    consumer_failed = consumer_task in done
    if consumer_failed:
        logger.error("Consumer loop stopped on its own, shutting down render worker")
        stop_task.cancel()
    else:
        logger.info("Shutdown signal received, stopping render worker")
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    await close_auth_client()
    await close_producer()
    await close_pool()

    if consumer_failed:
        # Пробрасываем причину наружу — ненулевой код выхода и запись в Sentry.
        consumer_task.result()


if __name__ == "__main__":
    asyncio.run(main())
