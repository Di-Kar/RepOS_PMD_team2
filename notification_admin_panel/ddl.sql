-- ============================================================
-- DDL: Notification Service Database
-- PostgreSQL 15+
-- ============================================================

-- Расширение для UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. Шаблоны сообщений (CRUD для менеджеров)
-- ============================================================
CREATE TABLE message_templates (
    id              BIGSERIAL       PRIMARY KEY,
    name            VARCHAR(255)    NOT NULL,
    channel         VARCHAR(10)     NOT NULL DEFAULT 'email'
                        CHECK (channel IN ('email', 'sms', 'push')),
    subject         VARCHAR(500)    NOT NULL DEFAULT '',
    body            TEXT            NOT NULL,
    available_variables JSONB       NOT NULL DEFAULT '[]'::jsonb,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE message_templates IS 'Шаблоны сообщений для рассылок';

-- ============================================================
-- 2. Отрендеренный контент уведомлений (content_id)
-- ============================================================
CREATE TABLE notification_contents (
    content_id      UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    template_id     BIGINT          REFERENCES message_templates(id)
                        ON DELETE SET NULL,
    rendered_subject VARCHAR(500)   NOT NULL DEFAULT '',
    rendered_body   TEXT            NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE notification_contents IS 'Готовый отрендеренный контент';

-- ============================================================
-- 3. Кампании / Рассылки (создаются менеджерами)
-- ============================================================
CREATE TABLE campaigns (
    id                      BIGSERIAL       PRIMARY KEY,
    name                    VARCHAR(255)    NOT NULL,
    template_id             BIGINT          NOT NULL
                                REFERENCES message_templates(id)
                                ON DELETE RESTRICT,
    delivery_channel        VARCHAR(10)     NOT NULL DEFAULT 'email'
                                CHECK (delivery_channel IN ('email','sms','push')),
    schedule_type           VARCHAR(20)     NOT NULL DEFAULT 'immediate'
                                CHECK (schedule_type IN ('immediate','delayed','recurring')),
    delay_hours             INTEGER         CHECK (delay_hours IS NULL OR delay_hours >= 1),
    cron_expression         VARCHAR(100)    NOT NULL DEFAULT '',
    recurrence_description  VARCHAR(255)    NOT NULL DEFAULT '',
    recipient_ids           JSONB           NOT NULL DEFAULT '[]'::jsonb,
    status                  VARCHAR(20)     NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','scheduled','sending','sent','cancelled')),
    created_by_id           UUID            REFERENCES auth_user(id)
                                ON DELETE SET NULL,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE campaigns IS 'Рассылки, созданные менеджерами';

-- ============================================================
-- 4. Периодичность уведомлений (для recurring-кампаний)
-- ============================================================
CREATE TABLE notification_schedules (
    id              BIGSERIAL       PRIMARY KEY,
    campaign_id     BIGINT          NOT NULL UNIQUE
                        REFERENCES campaigns(id) ON DELETE CASCADE,
    cron_expression VARCHAR(100)    NOT NULL,
    next_run        TIMESTAMPTZ,
    last_run        TIMESTAMPTZ,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE
);

COMMENT ON TABLE notification_schedules IS 'Расписание повторяющихся рассылок';

-- ============================================================
-- 5. Уведомления (notification_id + content_id)
-- ============================================================
CREATE TABLE notifications (
    notification_id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id              UUID        NOT NULL
                                REFERENCES notification_contents(content_id)
                                ON DELETE RESTRICT,
    campaign_id             BIGINT      REFERENCES campaigns(id)
                                ON DELETE SET NULL,
    user_id                 UUID        NOT NULL,
    channel                 VARCHAR(10) NOT NULL
                                CHECK (channel IN ('email','sms','push')),
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','sending','sent','failed')),
    scheduled_at            TIMESTAMPTZ NOT NULL,
    sent_at                 TIMESTAMPTZ,
    last_update             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_notification_send  TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE notifications IS 'Индивидуальные уведомления пользователям';

CREATE INDEX idx_notifications_status_scheduled
    ON notifications (status, scheduled_at)
    WHERE status = 'pending';

CREATE INDEX idx_notifications_user
    ON notifications (user_id);

-- ============================================================
-- 6. История отправки уведомлений
-- ============================================================
CREATE TABLE notification_history (
    id                  BIGSERIAL       PRIMARY KEY,
    notification_id     UUID            NOT NULL
                            REFERENCES notifications(notification_id)
                            ON DELETE CASCADE,
    status              VARCHAR(20)     NOT NULL,
    sent_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    error_message       TEXT            NOT NULL DEFAULT '',
    delivery_provider   VARCHAR(50)     NOT NULL DEFAULT ''
);

COMMENT ON TABLE notification_history IS 'Лог всех попыток отправки';

CREATE INDEX idx_history_notification
    ON notification_history (notification_id);
