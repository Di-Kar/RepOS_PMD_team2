"""add profile fields

Revision ID: b58f3a12d7e4
Revises: a7c9e24f6b31
Create Date: 2026-10-04 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b58f3a12d7e4'
down_revision = 'a7c9e24f6b31'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('first_name', sa.String(length=100), nullable=False))
    op.add_column('profiles', sa.Column('last_name', sa.String(length=100), nullable=False))
    op.add_column('profiles', sa.Column('phone', sa.String(length=32), nullable=False))
    op.add_column(
        'profiles',
        sa.Column(
            'phone_verified',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    op.create_unique_constraint('uq_profiles_phone', 'profiles', ['phone'])


def downgrade() -> None:
    op.drop_constraint('uq_profiles_phone', 'profiles', type_='unique')
    op.drop_column('profiles', 'phone_verified')
    op.drop_column('profiles', 'phone')
    op.drop_column('profiles', 'last_name')
    op.drop_column('profiles', 'first_name')
