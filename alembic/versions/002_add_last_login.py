"""Add users.last_login column

Revision ID: 002_add_last_login
Revises: 001_initial
Create Date: 2026-01-13

This migration adds the last_login column to the users table.
The column is nullable so it won't break existing data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_add_last_login'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add last_login column to users table.
    Using nullable=True so existing rows are not affected.
    """
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    if is_postgres:
        # PostgreSQL: Use IF NOT EXISTS via raw SQL for safety
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'last_login'
                ) THEN
                    ALTER TABLE users ADD COLUMN last_login TIMESTAMP;
                END IF;
            END $$;
        """)
    else:
        # SQLite: Simple add (may fail if exists, which is fine)
        try:
            op.add_column('users', sa.Column('last_login', sa.DateTime(), nullable=True))
        except Exception:
            pass  # Column already exists


def downgrade() -> None:
    """
    Remove last_login column from users table.
    WARNING: This will lose all last_login data!
    """
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    if is_postgres:
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login")
    else:
        # SQLite doesn't support DROP COLUMN easily
        pass
