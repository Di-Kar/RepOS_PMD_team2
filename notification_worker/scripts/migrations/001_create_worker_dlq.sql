-- Собственная таблица notification_worker: сообщения, которые не удалось
-- обработать (постоянная ошибка) или которые требуют ручного разбора
-- (неоднозначное состояние 'sending' после падения процесса).
--
-- Ни notification_log (нет данных для строки, если даже профиль не
-- получен — notification_id известен, но детали заявки не всегда), ни
-- notifications/notification_history (жёсткий FK: notifications.content_id
-- NOT NULL REFERENCES notification_contents — нельзя вставить строку без
-- готового контента) не годятся для этого случая.
CREATE TABLE IF NOT EXISTS notification_worker_dlq (
    id               BIGSERIAL PRIMARY KEY,
    notification_id  UUID,
    stage            VARCHAR(20) NOT NULL,   -- 'render' | 'send'
    error_type       VARCHAR(100) NOT NULL,  -- user_not_found / template_not_found / invalid_message / smtp_permanent / send_ambiguous ...
    error_message    TEXT NOT NULL DEFAULT '',
    raw_message      JSONB,
    attempt_count    INT NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_worker_dlq_notification_id
    ON notification_worker_dlq (notification_id);
