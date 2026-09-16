"""initial

Revision ID: f3a8c1d92b47
Revises:
Create Date: 2026-09-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f3a8c1d92b47'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notification_log',
        sa.Column('notification_id', sa.UUID(), nullable=False),
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('source_service', sa.String(length=255), nullable=False),
        sa.Column('campaign_id', sa.String(length=255), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('template_id', sa.String(length=255), nullable=True),
        sa.Column('subject_override', sa.Text(), nullable=True),
        sa.Column('text_override', sa.Text(), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column(
            'status_updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('notification_id'),
    )
    op.create_index(
        op.f('ix_notification_log_request_id'),
        'notification_log',
        ['request_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_notification_log_user_id'),
        'notification_log',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_notification_log_status'),
        'notification_log',
        ['status'],
        unique=False,
    )

    # status_updated_at должен обновляться при любом UPDATE строки, в т.ч. от
    # notification_worker — отдельного сервиса, который не обязан ходить через
    # ORM notification_api. DB-триггер, а не Python onupdate (см. entity.py).
    op.execute(
        """
        CREATE FUNCTION notification_log_set_status_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.status_updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notification_log_status_updated_at
        BEFORE UPDATE ON notification_log
        FOR EACH ROW
        EXECUTE FUNCTION notification_log_set_status_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_notification_log_status_updated_at ON notification_log"
    )
    op.execute("DROP FUNCTION IF EXISTS notification_log_set_status_updated_at()")
    op.drop_index(op.f('ix_notification_log_status'), table_name='notification_log')
    op.drop_index(op.f('ix_notification_log_user_id'), table_name='notification_log')
    op.drop_index(op.f('ix_notification_log_request_id'), table_name='notification_log')
    op.drop_table('notification_log')
