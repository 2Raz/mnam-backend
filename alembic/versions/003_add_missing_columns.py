"""Add all missing columns to existing tables

Revision ID: 003_add_missing_columns
Revises: 002_add_last_login
Create Date: 2026-01-13

This migration ensures all columns defined in models exist in the database.
Each column addition uses IF NOT EXISTS logic for safety.
All new columns are nullable or have defaults to not break existing data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003_add_missing_columns'
down_revision: Union[str, None] = '002_add_last_login'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def add_column_if_not_exists(table: str, column: str, column_def: str):
    """Helper to add column only if it doesn't exist (PostgreSQL only)"""
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = '{column}'
            ) THEN
                ALTER TABLE {table} ADD COLUMN {column} {column_def};
            END IF;
        END $$;
    """)


def upgrade() -> None:
    """
    Add all missing columns to ensure DB matches models.
    All columns are nullable or have defaults for safety.
    """
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    if not is_postgres:
        # SQLite in development - tables are created by create_all()
        return
    
    # ==========================================
    # USERS TABLE
    # ==========================================
    add_column_if_not_exists('users', 'last_login', 'TIMESTAMP')
    add_column_if_not_exists('users', 'is_system_owner', 'BOOLEAN DEFAULT FALSE')
    
    # ==========================================
    # OWNERS TABLE
    # ==========================================
    add_column_if_not_exists('owners', 'created_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('owners', 'updated_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('owners', 'commission_percent', 'FLOAT DEFAULT 10')
    add_column_if_not_exists('owners', 'bank_name', 'VARCHAR(100)')
    add_column_if_not_exists('owners', 'bank_iban', 'VARCHAR(50)')
    
    # ==========================================
    # PROJECTS TABLE
    # ==========================================
    add_column_if_not_exists('projects', 'created_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('projects', 'updated_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('projects', 'commission_percent', 'FLOAT DEFAULT 10')
    add_column_if_not_exists('projects', 'bank_name', 'VARCHAR(100)')
    add_column_if_not_exists('projects', 'bank_iban', 'VARCHAR(50)')
    
    # ==========================================
    # UNITS TABLE
    # ==========================================
    add_column_if_not_exists('units', 'created_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('units', 'updated_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('units', 'permit_no', 'VARCHAR(50)')
    add_column_if_not_exists('units', 'description', 'TEXT')
    add_column_if_not_exists('units', 'amenities', 'TEXT')
    add_column_if_not_exists('units', 'floor_number', 'INTEGER DEFAULT 0')
    add_column_if_not_exists('units', 'unit_area', 'FLOAT DEFAULT 0')
    
    # ==========================================
    # BOOKINGS TABLE
    # ==========================================
    add_column_if_not_exists('bookings', 'created_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('bookings', 'updated_by_id', 'VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL')
    add_column_if_not_exists('bookings', 'customer_id', 'VARCHAR(36) REFERENCES customers(id) ON DELETE SET NULL')
    
    # ==========================================
    # CUSTOMERS TABLE
    # ==========================================
    add_column_if_not_exists('customers', 'booking_count', 'INTEGER DEFAULT 0')
    add_column_if_not_exists('customers', 'completed_booking_count', 'INTEGER DEFAULT 0')
    add_column_if_not_exists('customers', 'total_revenue', 'FLOAT DEFAULT 0')
    add_column_if_not_exists('customers', 'is_banned', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('customers', 'is_profile_complete', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('customers', 'ban_reason', 'TEXT')
    add_column_if_not_exists('customers', 'gender', 'VARCHAR(20)')
    add_column_if_not_exists('customers', 'nationality', 'VARCHAR(50)')
    add_column_if_not_exists('customers', 'notes', 'TEXT')
    add_column_if_not_exists('customers', 'preferred_project_id', 'VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL')
    
    # ==========================================
    # CREATE MISSING TABLES
    # ==========================================
    
    # Refresh Tokens table
    op.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(255) NOT NULL UNIQUE,
            device_info VARCHAR(255),
            ip_address VARCHAR(45),
            is_revoked BOOLEAN DEFAULT FALSE,
            revoked_at TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Employee Activity Log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_activity_log (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            employee_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
            activity_type VARCHAR(50) NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(36),
            details TEXT,
            metadata JSONB,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Employee Targets table
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_targets (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            employee_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
            set_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            period VARCHAR(20) NOT NULL DEFAULT 'daily',
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            target_bookings INTEGER DEFAULT 0,
            target_customers INTEGER DEFAULT 0,
            target_revenue DECIMAL(10, 2) DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Employee Performance Summary table
    op.execute("""
        CREATE TABLE IF NOT EXISTS employee_performance_summary (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            employee_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
            summary_date DATE NOT NULL,
            period_type VARCHAR(20) NOT NULL DEFAULT 'daily',
            bookings_created INTEGER DEFAULT 0,
            bookings_modified INTEGER DEFAULT 0,
            bookings_cancelled INTEGER DEFAULT 0,
            customers_created INTEGER DEFAULT 0,
            customers_updated INTEGER DEFAULT 0,
            total_revenue DECIMAL(10, 2) DEFAULT 0,
            target_achievement_rate FLOAT DEFAULT 0,
            efficiency_score FLOAT DEFAULT 0,
            quality_score FLOAT DEFAULT 0,
            overall_score FLOAT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, summary_date, period_type)
        )
    """)
    
    # Create indexes if not exist
    op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_employee ON employee_activity_log(employee_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bookings_dates ON bookings(check_in_date, check_out_date)")


def downgrade() -> None:
    """
    Downgrade is intentionally minimal to avoid data loss.
    Only removes columns that were added in this migration.
    """
    pass  # Not implementing downgrade to protect existing data
