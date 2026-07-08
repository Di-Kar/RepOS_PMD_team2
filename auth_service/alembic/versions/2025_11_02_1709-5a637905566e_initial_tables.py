"""initial_tables

Revision ID: 5a637905566e
Revises: 
Create Date: 2025-11-02 17:09:58.402978

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5a637905566e'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create uuid-ossp extension for UUID generation
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('login', sa.String(255), nullable=False, unique=True),
        sa.Column('password', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(50), nullable=True),
        sa.Column('last_name', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create indexes for users table
    op.create_index('idx_users_login', 'users', ['login'])
    op.create_index('idx_users_is_active', 'users', ['is_active'])
    
    # Create roles table
    op.create_table(
        'roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Create index for roles table
    op.create_index('idx_roles_name', 'roles', ['name'])
    
    # Create user_roles table (many-to-many relationship)
    op.create_table(
        'user_roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role')
    )
    
    # Create indexes for user_roles table
    op.create_index('idx_user_roles_user_id', 'user_roles', ['user_id'])
    op.create_index('idx_user_roles_role_id', 'user_roles', ['role_id'])
    
    # Create login_history table
    op.create_table(
        'login_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('fingerprint', sa.String(255), nullable=True),
        sa.Column('login_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )
    
    # Create indexes for login_history table
    op.create_index('idx_login_history_user_id', 'login_history', ['user_id'])
    op.create_index('idx_login_history_login_at', 'login_history', ['login_at'])


def downgrade() -> None:
    # Drop tables in reverse order (to respect foreign keys)
    op.drop_index('idx_login_history_login_at', table_name='login_history')
    op.drop_index('idx_login_history_user_id', table_name='login_history')
    op.drop_table('login_history')
    
    op.drop_index('idx_user_roles_role_id', table_name='user_roles')
    op.drop_index('idx_user_roles_user_id', table_name='user_roles')
    op.drop_table('user_roles')
    
    op.drop_index('idx_roles_name', table_name='roles')
    op.drop_table('roles')
    
    op.drop_index('idx_users_is_active', table_name='users')
    op.drop_index('idx_users_login', table_name='users')
    op.drop_table('users')
    
    # Drop uuid-ossp extension
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
