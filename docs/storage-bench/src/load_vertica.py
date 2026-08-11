#!/usr/bin/env python3
"""
Загрузка данных в Vertica из CSV-файлов.
"""

import argparse
import time
import warnings
from pathlib import Path

import vertica_python

from config import VERTICA

# Отключаем предупреждения Vertica
warnings.filterwarnings("ignore", message=".*Cannot commit.*")
warnings.filterwarnings("ignore", message=".*TLS is not configured.*")


DDL_STATEMENTS = [
    "CREATE SCHEMA IF NOT EXISTS bench",
    """
    CREATE TABLE IF NOT EXISTS bench.events (
        event_id BIGINT NOT NULL,
        event_time TIMESTAMPTZ NOT NULL,
        user_id BIGINT NOT NULL,
        event_type VARCHAR(20) NOT NULL,
        category VARCHAR(30) NOT NULL,
        device VARCHAR(20) NOT NULL,
        country VARCHAR(5) NOT NULL,
        amount NUMERIC(18, 2) NOT NULL
    )
    ORDER BY event_time, event_type, user_id
    SEGMENTED BY HASH(event_id) ALL NODES
    """,
]


def ensure_schema(cur):
    """Создаёт схему и таблицу, если их нет."""
    for stmt in DDL_STATEMENTS:
        cur.execute(stmt)
    print("[Vertica] Схема и таблица готовы")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datadir", default="data/csv")
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument(
        "--truncate",
        action="store_true",
        default=True,
        help="Очистить таблицу перед загрузкой (по умолчанию True)",
    )
    args = parser.parse_args()

    files = sorted(Path(args.datadir).glob("part_*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {args.datadir}")

    conn_params = dict(VERTICA)
    conn_params["tlsmode"] = "disable"
    conn_params["autocommit"] = True

    conn = vertica_python.connect(**conn_params)
    cur = conn.cursor()

    ensure_schema(cur)

    cur.execute("SET TIME ZONE 'UTC'")

    if args.truncate:
        cur.execute("TRUNCATE TABLE bench.events")
        print("[Vertica] Таблица очищена")

    start = time.perf_counter()
    total_loaded = 0

    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as fh:
            cur.copy(
                """
                COPY bench.events (
                    event_id,
                    event_time,
                    user_id,
                    event_type,
                    category,
                    device,
                    country,
                    amount
                )
                FROM STDIN
                DELIMITER ','
                NULL ''
                """,
                fh,
            )
        total_loaded += 1
        print(f"[Vertica] loaded {file_path.name}")

    # НЕ вызываем conn.commit() при autocommit=True

    elapsed = time.perf_counter() - start
    rows_per_sec = args.total / elapsed if elapsed > 0 else 0

    print(
        "{"
        f'"db":"vertica",'
        f'"bulk_insert_rows":{args.total},'
        f'"seconds":{elapsed:.2f},'
        f'"rows_per_sec":{rows_per_sec:.0f}'
        "}"
    )

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
