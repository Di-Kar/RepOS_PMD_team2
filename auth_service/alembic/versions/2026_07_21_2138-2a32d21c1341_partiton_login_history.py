"""partiton_login_history

Revision ID: 2a32d21c1341
Revises: 60aa65d8a8a8
Create Date: 2026-07-21 21:38:15.630580

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a32d21c1341'
down_revision = '60aa65d8a8a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Заполняем user_device_type для существующих записей на основе user_agent
    op.execute("""
        UPDATE login_history
        SET user_device_type = CASE
            WHEN user_agent ILIKE '%mobile%'
                OR user_agent ILIKE '%android%'
                OR user_agent ILIKE '%iphone%'
                THEN 'mobile'
            WHEN user_agent ILIKE '%smart%'
                OR user_agent ILIKE '%tv%'
                THEN 'smart'
            ELSE 'web'
        END
        WHERE user_device_type IS NULL;
    """)

    # 2. Гарантируем, что поле NOT NULL (согласно модели SQLAlchemy)
    op.execute("ALTER TABLE login_history ALTER COLUMN user_device_type SET NOT NULL;")

    # 3. Переименовываем существующую таблицу
    op.execute("ALTER TABLE login_history RENAME TO login_history_old;")

    # 4. Создаем новую таблицу с поддержкой партиционирования (LIST)
    op.execute("""
        CREATE TABLE login_history (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            user_agent TEXT,
            ip_address VARCHAR(45),
            fingerprint VARCHAR(255),
            login_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            success BOOLEAN DEFAULT TRUE,
            user_device_type VARCHAR(20) NOT NULL,
            PRIMARY KEY (id, user_device_type)
        ) PARTITION BY LIST (user_device_type);
    """)

    # 5. Создаем физические партиции для каждого типа устройства
    op.execute("""
        CREATE TABLE login_history_web
        PARTITION OF login_history
        FOR VALUES IN ('web');
    """)

    op.execute("""
        CREATE TABLE login_history_mobile
        PARTITION OF login_history
        FOR VALUES IN ('mobile');
    """)

    op.execute("""
        CREATE TABLE login_history_smart
        PARTITION OF login_history
        FOR VALUES IN ('smart');
    """)

    # 6. Копируем данные из старой таблицы в новую
    op.execute("INSERT INTO login_history SELECT * FROM login_history_old;")

    # 7. Восстанавливаем внешний ключ
    op.execute("""
        ALTER TABLE login_history
        ADD CONSTRAINT login_history_user_id_fkey
        FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE;
    """)

    # 8. Создаем индексы на каждой партиции отдельно
    # Это дает больше гибкости и позволяет оптимизировать индексы под конкретные партиции

    # Индексы для партиции web
    op.execute("""
        CREATE INDEX idx_login_history_web_user_id
        ON login_history_web (user_id);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_web_login_at
        ON login_history_web (login_at);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_web_user_device_type
        ON login_history_web (user_device_type);
    """)

    # Индексы для партиции mobile
    op.execute("""
        CREATE INDEX idx_login_history_mobile_user_id
        ON login_history_mobile (user_id);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_mobile_login_at
        ON login_history_mobile (login_at);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_mobile_user_device_type
        ON login_history_mobile (user_device_type);
    """)

    # Индексы для партиции smart
    op.execute("""
        CREATE INDEX idx_login_history_smart_user_id
        ON login_history_smart (user_id);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_smart_login_at
        ON login_history_smart (login_at);
    """)
    op.execute("""
        CREATE INDEX idx_login_history_smart_user_device_type
        ON login_history_smart (user_device_type);
    """)

    # 9. Удаляем старую таблицу
    op.execute("DROP TABLE login_history_old;")


def downgrade() -> None:
    # При откате миграции выполняем обратный процесс

    op.execute("ALTER TABLE login_history RENAME TO login_history_part;")

    op.execute("""
        CREATE TABLE login_history (
            id UUID NOT NULL,
            user_id UUID NOT NULL,
            user_agent TEXT,
            ip_address VARCHAR(45),
            fingerprint VARCHAR(255),
            login_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            success BOOLEAN DEFAULT TRUE,
            user_device_type VARCHAR(20) NOT NULL,
            PRIMARY KEY (id, user_device_type)
        );
    """)

    op.execute("INSERT INTO login_history SELECT * FROM login_history_part;")

    op.execute("ALTER TABLE login_history ADD CONSTRAINT login_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;")

    # Создаем индексы на обычной таблице
    op.execute("CREATE INDEX idx_login_history_user_id ON login_history (user_id);")
    op.execute("CREATE INDEX idx_login_history_login_at ON login_history (login_at);")
    op.execute("CREATE INDEX idx_login_history_device_type ON login_history (user_device_type);")

    op.execute("DROP TABLE login_history_part;")
