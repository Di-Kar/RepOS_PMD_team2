"""add_user_is_password_set

Revision ID: 9d1c4a7e6b3f
Revises: 7b3f9c1d8a2e
Create Date: 2026-07-25 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9d1c4a7e6b3f'
down_revision = '7b3f9c1d8a2e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('is_password_set', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade() -> None:
    op.drop_column('users', 'is_password_set')
