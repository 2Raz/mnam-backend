"""Add employee_sessions and employee_attendance tables

Revision ID: 004_add_employee_sessions
Revises: 003_add_missing_columns
Create Date: 2026-01-21

This migration adds tables for tracking employee sessions and daily attendance:
- employee_sessions: tracks individual login sessions
- employee_attendance: daily attendance summary per employee
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision: str = '004_add_employee_sessions'
down_revision: Union[str, None] = '003_add_missing_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add employee_sessions and employee_attendance tables."""
    
    # Create employee_sessions table
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS employee_sessions (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            login_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            logout_at TIMESTAMP,
            last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_minutes INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            ip_address VARCHAR(50),
            user_agent VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # Create index on employee_id
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_employee_sessions_employee_id 
        ON employee_sessions(employee_id)
    """))
    
    # Create index on is_active
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_employee_sessions_is_active 
        ON employee_sessions(is_active)
    """))
    
    # Create employee_attendance table
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS employee_attendance (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            first_login TIMESTAMP,
            last_logout TIMESTAMP,
            last_activity TIMESTAMP,
            total_sessions INTEGER DEFAULT 0,
            total_duration_minutes INTEGER DEFAULT 0,
            activities_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_employee_date UNIQUE(employee_id, date)
        )
    """))
    
    # Create indexes
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_employee_attendance_employee_id 
        ON employee_attendance(employee_id)
    """))
    
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_employee_attendance_date 
        ON employee_attendance(date)
    """))


def downgrade() -> None:
    """Remove employee_sessions and employee_attendance tables."""
    op.execute(text("DROP TABLE IF EXISTS employee_sessions CASCADE"))
    op.execute(text("DROP TABLE IF EXISTS employee_attendance CASCADE"))
