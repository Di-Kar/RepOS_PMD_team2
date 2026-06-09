"""ETL-пайплайн."""
import logging
import random
import time
import psycopg2
from psycopg2 import OperationalError
from elasticsearch.exceptions import ConnectionError

from app.config import AppConfig
from app.extract import PostgresExtractor
from app.transform import DataTransformer
from app.load import ElasticsearchLoader
from app.state import StateStorage

logger = logging.getLogger(__name__)
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
RETRYABLE_ERRORS = (OperationalError, ConnectionError)


class ETLPipeline:
    def __init__(self, config: AppConfig):
        self.config = config
        self.state = StateStorage()
        self.extractor = PostgresExtractor(config.pg_dsn)
        self.transformer = DataTransformer()
        self.loader = ElasticsearchLoader(config.es_dsn, config.es_index_name)
        self.max_retries = config.max_retries

    def _run_with_backoff(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except RETRYABLE_ERRORS as e:
                delay = (2 ** attempt) + random.uniform(0, 1.0)
                logger.warning(f" Попытка {attempt+1}/{self.max_retries}: {e}. Ждём {delay:.2f}с...")
                time.sleep(delay)
            except Exception as e:
                logger.error(f" Неожиданная ошибка: {e}", exc_info=True)
                raise
        raise RuntimeError("Превышено количество попыток.")

    def _run_cycle(self) -> None:
        logger.info("🚀 Запуск ETL-цикла.")
        if self._run_with_backoff(self.loader.create_index_if_not_exists):
            self.state.clear()

        last_film_id = self.state.get_cursor("film_work") or ZERO_UUID
        last_genre_id = self.state.get_cursor("genre") or ZERO_UUID
        last_person_id = self.state.get_cursor("person") or ZERO_UUID

        conn = psycopg2.connect(self.config.pg_dsn)
        conn.set_client_encoding("UTF8")
        try:
            batch_count = 0

            affected_ids = self._run_with_backoff(
                self.extractor.fetch_affected_by_related_ids,
                conn, last_genre_id, last_person_id
            )
            if affected_ids:
                logger.info(f" Найдено {len(affected_ids)} фильмов с новыми связанными записями")
                affected_docs = self._run_with_backoff(self.extractor.fetch_by_ids, conn, affected_ids)
                if affected_docs:
                    docs = self.transformer.transform(affected_docs)
                    self._run_with_backoff(self.loader.load_documents, docs, self.config.es_bulk_size)
                    logger.info(f" Переиндексировано {len(docs)} фильмов")

                cur = conn.cursor()
                cur.execute("SELECT id FROM content.genre ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                new_genre_id = str(row[0]) if row and row[0] else last_genre_id
                cur.execute("SELECT id FROM content.person ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                new_person_id = str(row[0]) if row and row[0] else last_person_id
                cur.close()

                self.state.update_cursor("genre", new_genre_id)
                self.state.update_cursor("person", new_person_id)
                last_genre_id, last_person_id = new_genre_id, new_person_id

            # 🔹 2. Основная пагинация по film_work.id
            while True:
                raw_data = self._run_with_backoff(
                    self.extractor.fetch_main_batch, conn, last_film_id, self.config.pg_fetch_size
                )
                if not raw_data:
                    msg = "Нет новых данных." if batch_count == 0 else f"Все данные обработаны. Пачек: {batch_count}."
                    logger.info(msg)
                    break

                docs = self.transformer.transform(raw_data)
                self._run_with_backoff(self.loader.load_documents, docs, self.config.es_bulk_size)
                batch_count += 1

                max_id = max(str(row["id"]) for row in raw_data)
                last_film_id = max_id
                self.state.update_cursor("film_work", last_film_id)
                logger.info(f"📦 Пачка №{batch_count} завершена. Курсор: {last_film_id}")

        finally:
            conn.close()
        logger.info("✅ ETL-цикл завершён.")

    def run(self) -> None:
        logger.info("🟢 Сервис ETL запущен.")
        while True:
            try:
                self._run_cycle()
            except Exception as e:
                logger.error(f"🔥 Критическая ошибка: {e}", exc_info=True)
            time.sleep(self.config.poll_interval_seconds)
