"""initial

Revision ID: c4a19f6e2b03
Revises:
Create Date: 2026-09-20 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4a19f6e2b03'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'short_links',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('owner_user_id', sa.UUID(), nullable=True),
        sa.Column('redirect_url', sa.Text(), nullable=False),
        sa.Column(
            'purpose', sa.String(length=50), nullable=False, server_default='generic'
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('visit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_visited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_visited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_service', sa.String(length=50), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_short_links_code'), 'short_links', ['code'], unique=True
    )
    op.create_index(
        op.f('ix_short_links_owner_user_id'),
        'short_links',
        ['owner_user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_short_links_expires_at'), 'short_links', ['expires_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_short_links_expires_at'), table_name='short_links')
    op.drop_index(op.f('ix_short_links_owner_user_id'), table_name='short_links')
    op.drop_index(op.f('ix_short_links_code'), table_name='short_links')
    op.drop_table('short_links')
