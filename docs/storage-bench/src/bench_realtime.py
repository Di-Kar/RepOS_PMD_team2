#!/usr/bin/env python3
import argparse
import json
import statistics
import threading
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


def bench_realtime(db, duration_seconds, batch_rows, interval_seconds):
    stop_event = threading.Event()
    read_latencies_ms = []

    writer_stats = {
        "rows": 0,
        "insert_latencies_ms": [],
    }

    def writer():
        conn = connect(db)
        end_time = time.time() + duration_seconds
        next_tick = time.time()

        while not stop_event.is_set() and time.time() < end_time:
            rows = make_rows(batch_rows)

            start = time.perf_counter()
            insert_rows(conn, db, rows)
            elapsed_ms = (time.perf_counter() - start) * 1000

            writer_stats["rows"] += len(rows)
            writer_stats["insert_latencies_ms"].append(elapsed_ms)

            next_tick += interval_seconds
            sleep_time = next_tick - time.time()

            if sleep_time > 0 and not stop_event.is_set():
                time.sleep(sleep_time)

        stop_event.set()

    def reader():
        conn = connect(db)
        end_time = time.time() + duration_seconds

        while not stop_event.is_set() and time.time() < end_time:
            start = time.perf_counter()
            fetch_all(conn, db)
            elapsed_ms = (time.perf_counter() - start) * 1000
            read_latencies_ms.append(elapsed_ms)

    writer_thread = threading.Thread(target=writer, daemon=True)
    reader_thread = threading.Thread(target=reader, daemon=True)

    start_all = time.perf_counter()

    writer_thread.start()
    reader_thread.start()

    writer_thread.join()
    reader_thread.join(timeout=duration_seconds + 60)

    total_seconds = time.perf_counter() - start_all

    if not read_latencies_ms:
        raise RuntimeError("No read queries completed during realtime test")

    read_avg = statistics.mean(read_latencies_ms)
    read_p95 = percentile(read_latencies_ms, 0.95)
    read_max = max(read_latencies_ms)

    insert_avg = statistics.mean(writer_stats["insert_latencies_ms"])
    insert_p95 = percentile(writer_stats["insert_latencies_ms"], 0.95)
    insert_max = max(writer_stats["insert_latencies_ms"])

    result = {
        "db": db,
        "duration_s": round(total_seconds, 2),
        "writer": {
            "inserted_rows": writer_stats["rows"],
            "rows_per_sec": round(writer_stats["rows"] / total_seconds, 1),
            "insert_avg_ms": round(insert_avg, 1),
            "insert_p95_ms": round(insert_p95, 1),
            "insert_max_ms": round(insert_max, 1),
        },
        "read_under_load": {
            "queries": len(read_latencies_ms),
            "avg_ms": round(read_avg, 1),
            "p95_ms": round(read_p95, 1),
            "max_ms": round(read_max, 1),
        },
        "sla_read_max_lt_10s": read_max < 10000,
    }

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        required=True,
        choices=["clickhouse", "postgres", "vertica"],
    )
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--batch-rows", type=int, default=1000)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    result = bench_realtime(
        db=args.db,
        duration_seconds=args.duration,
        batch_rows=args.batch_rows,
        interval_seconds=args.interval,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["sla_read_max_lt_10s"]:
        raise SystemExit("FAILED: aggregate query max latency is >= 10 seconds")


if __name__ == "__main__":
    main()
