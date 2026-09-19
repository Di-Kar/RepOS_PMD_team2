"""Идемпотентный DDL-раннер для собственной(-ых) таблицы(-иц) воркера.

Не Alembic и не Django migrate — у notifications_db уже есть две системы
миграций (Alembic в notification_api, Django в notification_admin_panel);
заводить третью ради одной таблицы notification_worker_dlq избыточно.
Вместо этого — простой скрипт, применяющий .sql-файлы из
scripts/migrations/ по порядку имени; каждый файл сам идемпотентен
(`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`), поэтому
повторный запуск безопасен и не требует таблицы версий.

Запускается одноразовым сервисом `notification_worker_migrations` в
docker-compose.yml, по образцу `notification_migrations` (alembic upgrade
head) у notification_api.
"""

import asyncio
import logging
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("notification_worker.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def run() -> None:
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("No migration files found in %s", MIGRATIONS_DIR)
        return

    conn = await asyncpg.connect(dsn=settings.postgres_dsn)
    try:
        for sql_file in sql_files:
            logger.info("Applying %s", sql_file.name)
            await conn.execute(sql_file.read_text(encoding="utf-8"))
    finally:
        await conn.close()

    logger.info("notification_worker migrations applied: %d file(s)", len(sql_files))


if __name__ == "__main__":
    asyncio.run(run())
