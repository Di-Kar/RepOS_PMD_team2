"""add profile view audit

Revision ID: c3d4e5f6a7b8
Revises: b58f3a12d7e4
Create Date: 2026-10-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b58f3a12d7e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'profile_view_audit',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('admin_email', sa.String(length=255), nullable=False),
        sa.Column('target_user_id', sa.UUID(), nullable=False),
        sa.Column(
            'viewed_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_profile_view_audit_target_user_id',
        'profile_view_audit',
        ['target_user_id'],
    )
    op.create_index(
        'idx_profile_view_audit_viewed_at',
        'profile_view_audit',
        ['viewed_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_profile_view_audit_viewed_at', table_name='profile_view_audit')
    op.drop_index('idx_profile_view_audit_target_user_id', table_name='profile_view_audit')
    op.drop_table('profile_view_audit')
