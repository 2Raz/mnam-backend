"""
Migration script to add missing columns to the database
Run this script to update the PostgreSQL database schema
"""
import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable not set")
    sys.exit(1)

# Handle Railway's postgres:// vs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"🔗 Connecting to database...")

engine = create_engine(DATABASE_URL)

# List of migrations to run
MIGRATIONS = [
    # Owners table - add tracking columns
    {
        "name": "Add created_by_id to owners",
        "sql": "ALTER TABLE owners ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    {
        "name": "Add updated_by_id to owners",
        "sql": "ALTER TABLE owners ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    
    # Projects table - add tracking columns
    {
        "name": "Add created_by_id to projects",
        "sql": "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    {
        "name": "Add updated_by_id to projects",
        "sql": "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    
    # Units table - add tracking columns
    {
        "name": "Add created_by_id to units",
        "sql": "ALTER TABLE units ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    {
        "name": "Add updated_by_id to units",
        "sql": "ALTER TABLE units ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    
    # Bookings table - add tracking columns
    {
        "name": "Add created_by_id to bookings",
        "sql": "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    {
        "name": "Add updated_by_id to bookings",
        "sql": "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL",
    },
    {
        "name": "Add customer_id to bookings",
        "sql": "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS customer_id VARCHAR(36) REFERENCES customers(id) ON DELETE SET NULL",
    },
    
    # Customers table - add new columns if missing
    {
        "name": "Add booking_count to customers",
        "sql": "ALTER TABLE customers ADD COLUMN IF NOT EXISTS booking_count INTEGER DEFAULT 0",
    },
    {
        "name": "Add is_banned to customers",
        "sql": "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE",
    },
    {
        "name": "Add ban_reason to customers",
        "sql": "ALTER TABLE customers ADD COLUMN IF NOT EXISTS ban_reason TEXT",
    },
    {
        "name": "Add gender to customers",
        "sql": "ALTER TABLE customers ADD COLUMN IF NOT EXISTS gender VARCHAR(20)",
    },
    
    # Employee Activity Log table
    {
        "name": "Create employee_activity_logs table",
        "sql": """
        CREATE TABLE IF NOT EXISTS employee_activity_logs (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            activity_type VARCHAR(50) NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(36),
            description TEXT,
            amount NUMERIC(12, 2) DEFAULT 0,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    },
    {
        "name": "Create index on employee_activity_logs employee_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_employee ON employee_activity_logs(employee_id)",
    },
    {
        "name": "Create index on employee_activity_logs created_at",
        "sql": "CREATE INDEX IF NOT EXISTS idx_activity_logs_created ON employee_activity_logs(created_at)",
    },
    
    # Employee Targets table
    {
        "name": "Create employee_targets table",
        "sql": """
        CREATE TABLE IF NOT EXISTS employee_targets (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            set_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            period VARCHAR(20) NOT NULL DEFAULT 'daily',
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            target_bookings INTEGER DEFAULT 0,
            target_booking_revenue NUMERIC(12, 2) DEFAULT 0,
            target_new_customers INTEGER DEFAULT 0,
            target_completion_rate NUMERIC(5, 2) DEFAULT 0,
            target_new_owners INTEGER DEFAULT 0,
            target_new_projects INTEGER DEFAULT 0,
            target_new_units INTEGER DEFAULT 0,
            notes TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    },
    {
        "name": "Create index on employee_targets employee_id",
        "sql": "CREATE INDEX IF NOT EXISTS idx_targets_employee ON employee_targets(employee_id)",
    },
    {
        "name": "Create index on employee_targets dates",
        "sql": "CREATE INDEX IF NOT EXISTS idx_targets_dates ON employee_targets(start_date, end_date)",
    },
    
    # Employee Performance Summary table
    {
        "name": "Create employee_performance_summary table",
        "sql": """
        CREATE TABLE IF NOT EXISTS employee_performance_summary (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            period_type VARCHAR(20) NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            total_activities INTEGER DEFAULT 0,
            bookings_created INTEGER DEFAULT 0,
            bookings_completed INTEGER DEFAULT 0,
            bookings_cancelled INTEGER DEFAULT 0,
            booking_revenue NUMERIC(12, 2) DEFAULT 0,
            new_customers INTEGER DEFAULT 0,
            new_owners INTEGER DEFAULT 0,
            new_projects INTEGER DEFAULT 0,
            new_units INTEGER DEFAULT 0,
            target_achievement_rate NUMERIC(5, 2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(employee_id, period_type, period_start)
        )
        """,
    },
]

def run_migrations():
    """Run all migrations"""
    print("🚀 Starting migrations...")
    
    with engine.connect() as conn:
        for migration in MIGRATIONS:
            try:
                print(f"  → Running: {migration['name']}...")
                conn.execute(text(migration['sql']))
                conn.commit()
                print(f"    ✅ Success")
            except ProgrammingError as e:
                if "already exists" in str(e) or "duplicate" in str(e).lower():
                    print(f"    ⏭️  Skipped (already exists)")
                else:
                    print(f"    ⚠️  Warning: {e}")
                conn.rollback()
            except Exception as e:
                print(f"    ❌ Error: {e}")
                conn.rollback()
    
    print("\n✅ Migration complete!")

if __name__ == "__main__":
    run_migrations()
