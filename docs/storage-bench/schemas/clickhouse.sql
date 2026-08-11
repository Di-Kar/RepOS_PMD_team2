CREATE DATABASE IF NOT EXISTS bench;

CREATE TABLE IF NOT EXISTS bench.events
(
    event_id UInt64,
    event_time DateTime64(3),
    user_id UInt64,
    event_type LowCardinality(String),
    category LowCardinality(String),
    device LowCardinality(String),
    country LowCardinality(String),
    amount Decimal(18, 2)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_type, event_time, user_id)
SETTINGS index_granularity = 8192; 
