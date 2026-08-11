CREATE INDEX IF NOT EXISTS events_time_brin
    ON bench.events USING BRIN (event_time);

CREATE INDEX IF NOT EXISTS events_type_time
    ON bench.events (event_type, event_time);

CREATE INDEX IF NOT EXISTS events_user_id
    ON bench.events (user_id);

ANALYZE bench.events;
