#!/usr/bin/env python3
import argparse
import time
from pathlib import Path

import psycopg2

from config import POSTGRES_DSN


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datadir", default="data/csv")
    parser.add_argument("--total", type=int, required=True)
    args = parser.parse_args()

    files = sorted(Path(args.datadir).glob("part_*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {args.datadir}")

    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = False

    cur = conn.cursor()
    cur.execute("SET TIME ZONE 'UTC'")
    cur.execute("TRUNCATE bench.events")

    start = time.perf_counter()

    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as fh:
            cur.copy_expert(
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
                FROM STDIN WITH (FORMAT CSV)
                """,
                fh,
            )
        print(f"loaded {file_path}")

    conn.commit()

    elapsed = time.perf_counter() - start
    rows_per_sec = args.total / elapsed

    print(
        "{"
        f'"db":"postgres",'
        f'"bulk_insert_rows":{args.total},'
        f'"seconds":{elapsed:.2f},'
        f'"rows_per_sec":{rows_per_sec:.0f}'
        "}"
    )

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
