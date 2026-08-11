#!/usr/bin/env python3
import argparse
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datadir", default="data/csv")
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--service", default="clickhouse")
    args = parser.parse_args()

    files = sorted(Path(args.datadir).glob("part_*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {args.datadir}")

    start = time.perf_counter()

    for file_path in files:
        cmd = [
            "docker",
            "compose",
            "exec",
            "-T",
            args.service,
            "clickhouse-client",
            "--database",
            "bench",
            "--query",
            "INSERT INTO bench.events FORMAT CSV",
            "--format_csv_delimiter",
            ",",
        ]

        with open(file_path, "rb") as fh:
            subprocess.run(cmd, stdin=fh, check=True)

        print(f"loaded {file_path}")

    elapsed = time.perf_counter() - start
    rows_per_sec = args.total / elapsed

    print(
        "{"
        f'"db":"clickhouse",'
        f'"bulk_insert_rows":{args.total},'
        f'"seconds":{elapsed:.2f},'
        f'"rows_per_sec":{rows_per_sec:.0f}'
        "}"
    )


if __name__ == "__main__":
    main()
