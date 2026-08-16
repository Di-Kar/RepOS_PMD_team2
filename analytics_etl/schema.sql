-- Raw events with deduplication (ReplacingMergeTree on occurred_at)
CREATE TABLE IF NOT EXISTS analytics.events (
    event_id String,
    event_type String,
    schema_version UInt8,
    occurred_at DateTime64(3),
    received_at DateTime64(3),
    user_id Nullable(String),
    anonymous_id Nullable(String),
    session_id String,
    sequence_number UInt64,
    consent UInt8,
    context_page_type String DEFAULT '',
    context_page_id String DEFAULT '',
    context_device String DEFAULT '',
    context_browser String DEFAULT '',
    context_app_version String DEFAULT '',
    source String DEFAULT '',
    custom_event_type Nullable(String),
    payload_content_id Nullable(String),
    payload_watch_session_id Nullable(String),
    payload_duration_ms Nullable(UInt64),
    payload_progress_percent Nullable(Float64),
    payload_from_quality Nullable(String),
    payload_to_quality Nullable(String),
    payload_tab_active Nullable(UInt8),
    raw_event String
) ENGINE = ReplacingMergeTree(occurred_at)
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (event_type, occurred_at, event_id)
TTL occurred_at + INTERVAL 90 DAY;

-- Aggregated movie metrics (supports: most watched, not completed)
CREATE TABLE IF NOT EXISTS analytics.movies_metrics (
    content_id String,
    total_views UInt64 DEFAULT 0,
    total_watch_sessions UInt64 DEFAULT 0,
    completions UInt64 DEFAULT 0,
    total_duration_ms UInt64 DEFAULT 0,
    unique_viewers UInt64 DEFAULT 0,
    last_viewed_at DateTime64(3) DEFAULT now(),
    updated_at DateTime64(3) DEFAULT now()
) ENGINE = SummingMergeTree()
ORDER BY content_id;

-- Watch sessions for quality/progress tracking
CREATE TABLE IF NOT EXISTS analytics.watch_sessions (
    watch_session_id String,
    content_id String,
    user_id Nullable(String),
    session_id String,
    started_at DateTime64(3),
    last_updated_at DateTime64(3),
    quality String DEFAULT '',
    progress_percent Float64 DEFAULT 0,
    duration_total UInt64 DEFAULT 0
) ENGINE = ReplacingMergeTree(last_updated_at)
ORDER BY (watch_session_id, content_id);

-- Dead letter queue for invalid events
CREATE TABLE IF NOT EXISTS analytics.dead_letter_queue (
    event_id String,
    event_type String,
    error_type String,
    error_message String,
    raw_event String,
    rejected_at DateTime64(3) DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (rejected_at, event_id)
TTL rejected_at + INTERVAL 30 DAY;
