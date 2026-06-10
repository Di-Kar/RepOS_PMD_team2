import logging
from datetime import datetime, timezone
from apscheduler.schedulers.blocking import BlockingScheduler
import backoff_utils
from config import etl_settings, postgres_settings, es_settings
from extractor import PostgresExtractor
from loader import ElasticsearchLoader
from state import JsonFileStorage, State
from transformer import DataTransformer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

WATCHED_TABLES = ('film_work', 'person', 'genre')

# Начальные значения курсора: дата гарантированно раньше любых данных,
# nil UUID гарантированно меньше любого UUID для tie-breaking.
_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc).isoformat()
_MIN_UUID = '00000000-0000-0000-0000-000000000000'


def run_etl(
    extractor: PostgresExtractor,
    transformer: DataTransformer,
    loader: ElasticsearchLoader,
    state: State,
) -> None:
    for table in WATCHED_TABLES:
        cursor_modified = state.get_state(f'cursor_modified_{table}') or _MIN_DATETIME
        cursor_id = state.get_state(f'cursor_id_{table}') or _MIN_UUID
        logger.info('Проверка изменений в %s с курсора %s / %s', table, cursor_modified, cursor_id)

        for film_ids, new_modified, new_id in extractor.fetch_batches(
            table, cursor_modified, cursor_id, etl_settings.batch_size
        ):
            if film_ids:
                raw_rows = extractor.fetch_film_details(film_ids)
                movies = transformer.transform(raw_rows)
                loader.bulk_upsert(movies)

            # Курсор обновляется после успешной загрузки каждого батча,
            # а не после обработки всей таблицы — чтобы не пропустить
            # записи, появившиеся во время работы ETL.
            state.set_state(f'cursor_modified_{table}', new_modified)
            state.set_state(f'cursor_id_{table}', new_id)
            logger.info('Прогресс %s → %s / %s', table, new_modified, new_id)


if __name__ == '__main__':
    backoff_utils.configure(
        start_sleep_time=etl_settings.backoff_start_sleep_time,
        border_sleep_time=etl_settings.backoff_border_sleep_time,
        max_attempts=etl_settings.backoff_max_attempts,
    )

    storage = JsonFileStorage(etl_settings.state_file)
    state = State(storage)
    extractor = PostgresExtractor(postgres_settings)
    transformer = DataTransformer()
    loader = ElasticsearchLoader(es_settings)

    loader.ensure_index()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_etl,
        trigger='interval',
        seconds=etl_settings.sleep_interval,
        args=[extractor, transformer, loader, state],
        next_run_time=datetime.now(),
    )

    logger.info('ETL-сервис запущен, интервал=%d с', etl_settings.sleep_interval)
    scheduler.start()
