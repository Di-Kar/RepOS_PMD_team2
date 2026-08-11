#!/usr/bin/env python3
import argparse
import os
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

EVENT_TYPES = np.array(["view", "click", "purchase", "refund", "login"])
CATEGORIES = np.array(["electronics", "books", "clothing", "food", "travel"])
DEVICES = np.array(["ios", "android", "web", "desktop"])
COUNTRIES = np.array(["RU", "US", "DE", "CN", "BR", "IN"])

BASE_DATE = np.datetime64("2026-01-01T00:00:00")
SECONDS_90_DAYS = 90 * 24 * 60 * 60


def gen_chunk(args):
    chunk_id, start_id, rows, seed, outdir = args
    rng = np.random.default_rng(seed)

    ts = BASE_DATE + rng.integers(
        0,
        SECONDS_90_DAYS,
        size=rows,
        dtype=np.int64
    ).astype("timedelta64[s]")

    # amount в копейках/центах: от 1.00 до 10000.00
    amount_cents = rng.integers(100, 1_000_001, size=rows, dtype=np.int64)

    df = pd.DataFrame(
        {
            "event_id": np.arange(start_id, start_id + rows, dtype=np.int64),
            "event_time": ts,
            "user_id": rng.integers(1, 1_000_000, size=rows, dtype=np.int64),
            "event_type": rng.choice(EVENT_TYPES, size=rows),
            "category": rng.choice(CATEGORIES, size=rows),
            "device": rng.choice(DEVICES, size=rows),
            "country": rng.choice(COUNTRIES, size=rows),
            "amount": amount_cents / 100.0,
        }
    )

    out_path = Path(outdir) / f"part_{chunk_id:05d}.csv"
    df.to_csv(
        out_path,
        index=False,
        header=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )

    return str(out_path), rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=10_000_000)
    parser.add_argument("--chunk", type=int, default=500_000)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument("--outdir", default="data/csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    Path(args.outdir).mkdir(parents=True, exist_ok=True)

    tasks = []
    start = 0
    chunk_id = 0

    while start < args.total:
        rows = min(args.chunk, args.total - start)
        tasks.append(
            (
                chunk_id,
                start,
                rows,
                args.seed + chunk_id,
                args.outdir,
            )
        )
        start += rows
        chunk_id += 1

    with Pool(args.workers) as pool:
        for path, rows in pool.imap_unordered(gen_chunk, tasks):
            print(f"generated={path} rows={rows}")


if __name__ == "__main__":
    main()
