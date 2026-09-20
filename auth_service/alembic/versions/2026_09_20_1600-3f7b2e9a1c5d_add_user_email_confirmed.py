"""add_user_email_confirmed

Revision ID: 3f7b2e9a1c5d
Revises: 9d1c4a7e6b3f
Create Date: 2026-09-20 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f7b2e9a1c5d'
down_revision = '9d1c4a7e6b3f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'email_confirmed', sa.Boolean(), nullable=False, server_default='false'
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'email_confirmed')
