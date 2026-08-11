import os
from pathlib import Path

TOTAL_ROWS = int(os.getenv("TOTAL_ROWS", "10000000"))
BATCH_ROWS = int(os.getenv("BATCH_ROWS", "1000"))
DATA_DIR = Path(os.getenv("DATA_DIR", "data/csv"))

CLICKHOUSE = {
    "host": "localhost",
    "port": 9000,
    "user": "default",
    "password": "clickhouse123", 
    "database": "bench",
}

POSTGRES_DSN = (
    "dbname=bench user=postgres password=postgres "
    "host=localhost port=5432"
)

VERTICA = {
    "host": "localhost",
    "port": 5433,
    "user": "dbadmin",
    "password": "",
    "database": "docker",
    "tlsmode": "disable",
}
