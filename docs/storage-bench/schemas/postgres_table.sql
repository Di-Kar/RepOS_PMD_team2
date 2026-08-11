CREATE SCHEMA IF NOT EXISTS bench;

CREATE TABLE IF NOT EXISTS bench.events
(
    event_id BIGINT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    user_id BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    device TEXT NOT NULL,
    country TEXT NOT NULL,
    amount NUMERIC(18, 2) NOT NULL
);
