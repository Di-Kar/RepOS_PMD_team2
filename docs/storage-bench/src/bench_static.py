#!/usr/bin/env python3
import argparse
import json
import statistics
import time

from adapters import connect, fetch_all, insert_rows, make_rows


def percentile(values, p):
    if not values:
        return None

    values = sorted(values)
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)

    if f == c:
        return values[f]

    return values[f] + (values[c] - values[f]) * (k - f)


def bench_insert(db, batches, batch_rows):
    conn = connect(db)

    total_rows = 0
    latencies_ms = []

    start_all = time.perf_counter()

    for _ in range(batches):
        rows = make_rows(batch_rows)

        start = time.perf_counter()
        insert_rows(conn, db, rows)
        elapsed_ms = (time.perf_counter() - start) * 1000

        total_rows += len(rows)
        latencies_ms.append(elapsed_ms)

    total_seconds = time.perf_counter() - start_all

    return {
        "rows": total_rows,
        "seconds": round(total_seconds, 3),
        "rows_per_sec": round(total_rows / total_seconds, 1),
        "batch_avg_ms": round(statistics.mean(latencies_ms), 1),
        "batch_p95_ms": round(percentile(latencies_ms, 0.95), 1),
        "batch_max_ms": round(max(latencies_ms), 1),
    }


def bench_select(db, repeats, warmup):
    conn = connect(db)

    for _ in range(warmup):
        fetch_all(conn, db)

    latencies_ms = []

    for _ in range(repeats):
        start = time.perf_counter()
        fetch_all(conn, db)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies_ms.append(elapsed_ms)

    return {
        "avg_ms": round(statistics.mean(latencies_ms), 1),
        "p95_ms": round(percentile(latencies_ms, 0.95), 1),
        "max_ms": round(max(latencies_ms), 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        required=True,
        choices=["clickhouse", "postgres", "vertica"],
    )
    parser.add_argument("--insert-batches", type=int, default=10)
    parser.add_argument("--batch-rows", type=int, default=10000)
    parser.add_argument("--select-repeats", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args()

    result = {
        "db": args.db,
        "micro_batch_insert": bench_insert(
            args.db,
            args.insert_batches,
            args.batch_rows,
        ),
        "select": bench_select(
            args.db,
            args.select_repeats,
            args.warmup,
        ),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
