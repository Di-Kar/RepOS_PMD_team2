#!/usr/bin/env bash
set -euo pipefail

TOTAL_ROWS=${TOTAL_ROWS:-10000000}
CHUNK_ROWS=${CHUNK_ROWS:-500000}
WORKERS=${WORKERS:-8}
DURATION=${DURATION:-60}
REALTIME_BATCH=${REALTIME_BATCH:-1000}
REALTIME_INTERVAL=${REALTIME_INTERVAL:-0.5}

REPORT=report.jsonl
: > "$REPORT"

echo "=== Generate CSV ==="
python src/generate_csv.py \
  --total "$TOTAL_ROWS" \
  --chunk "$CHUNK_ROWS" \
  --workers "$WORKERS" \
  --outdir data/csv

echo "=== Load ClickHouse ==="
python src/load_clickhouse.py --datadir data/csv --total "$TOTAL_ROWS" | tee -a "$REPORT"

docker compose exec -T clickhouse clickhouse-client \
  --query="OPTIMIZE TABLE bench.events FINAL" || true

echo "=== Load PostgreSQL ==="
python src/load_postgres.py --datadir data/csv --total "$TOTAL_ROWS" | tee -a "$REPORT"

docker compose exec -T postgres psql -U postgres -d bench -f /schemas/postgres_indexes.sql


echo "=== Waiting for Vertica to start ==="
for i in {1..60}; do
  if docker compose exec -T vertica \
    su - dbadmin -c "/opt/vertica/bin/vsql -d docker -c 'SELECT 1'" > /dev/null 2>&1; then
    echo "Vertica is ready"
    break
  fi
  echo "Waiting... ($i/60)"
  sleep 5
done

echo "=== Load Vertica ==="
python src/load_vertica.py --datadir data/csv --total "$TOTAL_ROWS" | tee -a "$REPORT"


for db in clickhouse postgres vertica; do
  echo "=== Static benchmark: $db ==="
  python src/bench_static.py --db "$db" | tee -a "$REPORT"

  echo "=== Realtime benchmark: $db ==="
  python src/bench_realtime.py \
    --db "$db" \
    --duration "$DURATION" \
    --batch-rows "$REALTIME_BATCH" \
    --interval "$REALTIME_INTERVAL" \
    | tee -a "$REPORT"
done

echo "Done. Report saved to $REPORT"
