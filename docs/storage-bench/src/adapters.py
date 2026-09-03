import datetime
import random
from decimal import Decimal

import numpy as np
import psycopg2
import psycopg2.extras
import vertica_python
from clickhouse_driver import Client
from config import CLICKHOUSE, POSTGRES_DSN, VERTICA

EVENT_TYPES = ["view", "click", "purchase", "refund", "login"]
CATEGORIES = ["electronics", "books", "clothing", "food", "travel"]
DEVICES = ["ios", "android", "web", "desktop"]
COUNTRIES = ["RU", "US", "DE", "CN", "BR", "IN"]

BASE_TIME = datetime.datetime(2026, 1, 1, 0, 0, 0)
SECONDS_90_DAYS = 90 * 24 * 60 * 60

QUERY = {
    "clickhouse": """
        SELECT
            event_type,
            count() AS cnt,
            sum(amount) AS sum_amount,
            avg(amount) AS avg_amount,
            uniqExact(user_id) AS users
        FROM bench.events
        WHERE event_time >= '2026-01-01 00:00:00'
          AND event_time < '2026-02-01 00:00:00'
        GROUP BY event_type
    """,
    "postgres": """
        SELECT
            event_type,
            count(*) AS cnt,
            sum(amount) AS sum_amount,
            avg(amount) AS avg_amount,
            count(DISTINCT user_id) AS users
        FROM bench.events
        WHERE event_time >= TIMESTAMP '2026-01-01 00:00:00'
          AND event_time < TIMESTAMP '2026-02-01 00:00:00'
        GROUP BY event_type
    """,
    "vertica": """
        SELECT
            event_type,
            count(*) AS cnt,
            sum(amount) AS sum_amount,
            avg(amount) AS avg_amount,
            count(DISTINCT user_id) AS users
        FROM bench.events
        WHERE event_time >= '2026-01-01 00:00:00'
          AND event_time < '2026-02-01 00:00:00'
        GROUP BY event_type
    """,
}


def connect(db: str):
    if db == "clickhouse":
        return Client(**CLICKHOUSE)

    if db == "postgres":
        conn = psycopg2.connect(POSTGRES_DSN)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")
        return conn

    if db == "vertica":
        # Используем параметры из config.py, включая tlsmode=disable
        conn_params = dict(VERTICA)
        conn_params["autocommit"] = True
        conn = vertica_python.connect(**conn_params)
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")
        return conn

    raise ValueError(f"Unsupported db: {db}")


def fetch_all(conn, db: str):
    if db == "clickhouse":
        return conn.execute(QUERY[db])

    cur = conn.cursor()
    cur.execute(QUERY[db])
    return cur.fetchall()


def make_rows(n: int, seed: int | None = None):
    if seed is None:
        seed = random.SystemRandom().randint(0, 2**32 - 1)

    rng = np.random.default_rng(seed)

    ids = rng.integers(0, 2**63 - 1, size=n, dtype=np.int64)
    offsets = rng.integers(0, SECONDS_90_DAYS, size=n, dtype=np.int64)
    users = rng.integers(1, 1_000_000, size=n, dtype=np.int64)

    event_idx = rng.integers(0, len(EVENT_TYPES), size=n)
    category_idx = rng.integers(0, len(CATEGORIES), size=n)
    device_idx = rng.integers(0, len(DEVICES), size=n)
    country_idx = rng.integers(0, len(COUNTRIES), size=n)

    amount_cents = rng.integers(100, 1_000_001, size=n, dtype=np.int64)

    rows = []

    for i in range(n):
        rows.append(
            (
                int(ids[i]),
                BASE_TIME + datetime.timedelta(seconds=int(offsets[i])),
                int(users[i]),
                EVENT_TYPES[event_idx[i]],
                CATEGORIES[category_idx[i]],
                DEVICES[device_idx[i]],
                COUNTRIES[country_idx[i]],
                Decimal(int(amount_cents[i])) / Decimal(100),
            )
        )

    return rows


def insert_rows(conn, db: str, rows):
    if not rows:
        return

    if db == "clickhouse":
        conn.execute(
            "INSERT INTO bench.events VALUES",
            rows,
        )
        return

    if db == "postgres":
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO bench.events (
                event_id,
                event_time,
                user_id,
                event_type,
                category,
                device,
                country,
                amount
            )
            VALUES %s
            """,
            rows,
            page_size=len(rows),
        )
        return

    if db == "vertica":
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO bench.events (
                event_id,
                event_time,
                user_id,
                event_type,
                category,
                device,
                country,
                amount
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
        return

    raise ValueError(f"Unsupported db: {db}")
