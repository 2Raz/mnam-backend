"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-01-13

This is a baseline migration that represents the current database state.
It creates all existing tables if they don't exist.

Safety Notes:
- All operations use IF NOT EXISTS to avoid failures on existing DBs
- Foreign keys reference existing tables
- Default values provided where required
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables if they don't exist"""
    
    # Check if we're on PostgreSQL or SQLite
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    if is_postgres:
        # PostgreSQL version with IF NOT EXISTS
        
        # Users table
        op.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                username VARCHAR(50) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                hashed_password VARCHAR(255) NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                phone VARCHAR(20),
                role VARCHAR(50) DEFAULT 'customers_agent',
                is_active BOOLEAN DEFAULT TRUE,
                is_system_owner BOOLEAN DEFAULT FALSE,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Refresh tokens table
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
        
        # Owners table
        op.execute("""
            CREATE TABLE IF NOT EXISTS owners (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                owner_name VARCHAR(100) NOT NULL,
                owner_mobile_phone VARCHAR(20) NOT NULL,
                paypal_email VARCHAR(255),
                note TEXT,
                contract_no VARCHAR(50),
                contract_status VARCHAR(50) DEFAULT 'ساري',
                contract_duration INTEGER,
                commission_percent FLOAT DEFAULT 10,
                bank_name VARCHAR(100),
                bank_iban VARCHAR(50),
                created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Projects table
        op.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                owner_id VARCHAR(36) REFERENCES owners(id) ON DELETE SET NULL,
                name VARCHAR(100) NOT NULL,
                city VARCHAR(100),
                district VARCHAR(100),
                map_url VARCHAR(500),
                contract_no VARCHAR(50),
                contract_status VARCHAR(50) DEFAULT 'ساري',
                contract_duration INTEGER,
                commission_percent FLOAT DEFAULT 10,
                bank_name VARCHAR(100),
                bank_iban VARCHAR(50),
                created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Units table
        op.execute("""
            CREATE TABLE IF NOT EXISTS units (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                project_id VARCHAR(36) REFERENCES projects(id) ON DELETE CASCADE,
                unit_name VARCHAR(100) NOT NULL,
                unit_type VARCHAR(50) DEFAULT 'شاليه',
                rooms INTEGER DEFAULT 1,
                status VARCHAR(50) DEFAULT 'متاحة',
                price_days_of_week FLOAT DEFAULT 0,
                price_in_weekends FLOAT DEFAULT 0,
                permit_no VARCHAR(50),
                description TEXT,
                amenities TEXT,
                floor_number INTEGER DEFAULT 0,
                unit_area FLOAT DEFAULT 0,
                created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Customers table
        op.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                name VARCHAR(100) NOT NULL,
                phone VARCHAR(20) NOT NULL UNIQUE,
                email VARCHAR(255),
                gender VARCHAR(20),
                nationality VARCHAR(50),
                preferred_project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL,
                booking_count INTEGER DEFAULT 0,
                completed_booking_count INTEGER DEFAULT 0,
                total_revenue FLOAT DEFAULT 0,
                is_banned BOOLEAN DEFAULT FALSE,
                is_profile_complete BOOLEAN DEFAULT FALSE,
                ban_reason TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Bookings table
        op.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL,
                unit_id VARCHAR(36) REFERENCES units(id) ON DELETE CASCADE,
                customer_id VARCHAR(36) REFERENCES customers(id) ON DELETE SET NULL,
                guest_name VARCHAR(100) NOT NULL,
                guest_phone VARCHAR(20),
                check_in_date DATE NOT NULL,
                check_out_date DATE NOT NULL,
                total_price DECIMAL(10, 2) DEFAULT 0,
                status VARCHAR(50) DEFAULT 'مؤكد',
                notes TEXT,
                created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Transactions table
        op.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
                owner_id VARCHAR(36) REFERENCES owners(id) ON DELETE SET NULL,
                project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL,
                booking_id VARCHAR(36) REFERENCES bookings(id) ON DELETE SET NULL,
                amount DECIMAL(10, 2) NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                description TEXT,
                transaction_date DATE,
                payment_method VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        
        # Create indexes
        op.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_bookings_dates ON bookings(check_in_date, check_out_date)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_employee ON employee_activity_log(employee_id)")
        
    else:
        # SQLite version - simpler, tables created by SQLAlchemy
        # Just pass since SQLite uses create_all in development
        pass


def downgrade() -> None:
    """
    Downgrade removes all tables.
    WARNING: This will DELETE ALL DATA!
    Only use in development.
    """
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'
    
    if is_postgres:
        # Drop tables in reverse dependency order
        tables = [
            'employee_performance_summary',
            'employee_targets',
            'employee_activity_log',
            'transactions',
            'bookings',
            'customers',
            'units',
            'projects',
            'owners',
            'refresh_tokens',
            'users'
        ]
        for table in tables:
            op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    else:
        pass
