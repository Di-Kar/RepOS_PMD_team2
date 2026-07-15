"""add role permissions

Revision ID: a1b2c3d4e5f6
Revises: 4d774ddd1001
Create Date: 2026-07-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '4d774ddd1001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'roles',
        sa.Column(
            'permissions',
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade() -> None:
    op.drop_column('roles', 'permissions')
