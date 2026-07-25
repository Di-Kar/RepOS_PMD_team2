"""fix_users_roles_timestamp_defaults

users/roles.created_at/updated_at были NOT NULL без server_default —
проставляет now(), как и было объявлено в моделях.

Revision ID: 7b3f9c1d8a2e
Revises: 2a32d21c1341
Create Date: 2026-07-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b3f9c1d8a2e'
down_revision = '2a32d21c1341'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('users', 'roles'):
        for column in ('created_at', 'updated_at'):
            op.alter_column(
                table, column,
                server_default=sa.text('now()'),
                existing_type=sa.DateTime(),
                existing_nullable=False,
            )


def downgrade() -> None:
    for table in ('users', 'roles'):
        for column in ('created_at', 'updated_at'):
            op.alter_column(
                table, column,
                server_default=None,
                existing_type=sa.DateTime(),
                existing_nullable=False,
            )
