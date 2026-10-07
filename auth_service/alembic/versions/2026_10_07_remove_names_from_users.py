"""remove first_name and last_name from users

Revision ID: 7f8e9d0a1b2c
Revises: 3f7b2e9a1c5d
Create Date: 2026-10-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7f8e9d0a1b2c'
down_revision = '3f7b2e9a1c5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Удаляем колонки ФИО, так как они перенесены в user_profiles
    op.drop_column('users', 'first_name')
    op.drop_column('users', 'last_name')


def downgrade() -> None:
    # При откате возвращаем колонки.
    # Примечание: данные в этих колонках будут пустыми (NULL),
    # так как при drop_column они безвозвратно удаляются из БД.
    op.add_column('users', sa.Column('last_name', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('first_name', sa.String(length=50), nullable=True))
