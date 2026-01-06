import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Get database URL directly from environment variable
database_url = os.environ.get("DATABASE_URL")

# Debug: Print all environment variables starting with DATABASE or POSTGRES
print("=" * 50)
print("🔍 Checking environment variables...")
for key, value in os.environ.items():
    if "DATABASE" in key.upper() or "POSTGRES" in key.upper() or "PG" in key.upper():
        # Hide password in URL
        safe_value = value[:50] + "..." if len(value) > 50 else value
        print(f"   {key} = {safe_value}")
print("=" * 50)

# If no DATABASE_URL, check for Railway-specific variables
if not database_url:
    # Try Railway's internal PostgreSQL URL format
    pg_host = os.environ.get("PGHOST")
    pg_port = os.environ.get("PGPORT", "5432")
    pg_user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER")
    pg_password = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    pg_database = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB")
    
    if pg_host and pg_user and pg_password and pg_database:
        database_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
        print(f"✅ Built DATABASE_URL from PG* variables: {pg_host}:{pg_port}/{pg_database}")
    else:
        # Check if we're in production without a database
        if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("ENVIRONMENT") == "production":
            print("❌ ERROR: DATABASE_URL not set in production!")
            print("   Please add PostgreSQL to your Railway project and link DATABASE_URL")
            sys.exit(1)
        else:
            # Development mode - use SQLite
            database_url = "sqlite:///./mnam.db"
            print("⚠️  Using SQLite for development")

print(f"🔗 Using database: {database_url[:40]}...")

# Railway provides DATABASE_URL with postgres:// prefix, but SQLAlchemy needs postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# Handle SQLite special case for check_same_thread
connect_args = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Check if production
is_production = os.environ.get("ENVIRONMENT", "development") == "production"

engine = create_engine(
    database_url,
    connect_args=connect_args,
    echo=not is_production,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables in the database"""
    Base.metadata.create_all(bind=engine)


def run_migrations():
    """Run database migrations to add missing columns"""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    
    print("🔄 Running database migrations...")
    
    # Only run migrations for PostgreSQL (production)
    if not database_url.startswith("postgresql"):
        print("   ⏭️  Skipping migrations (SQLite mode)")
        return
    
    migrations = [
        # Owners table
        ("owners.created_by_id", "ALTER TABLE owners ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        ("owners.updated_by_id", "ALTER TABLE owners ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        
        # Projects table
        ("projects.created_by_id", "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        ("projects.updated_by_id", "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        
        # Units table
        ("units.created_by_id", "ALTER TABLE units ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        ("units.updated_by_id", "ALTER TABLE units ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        
        # Bookings table
        ("bookings.created_by_id", "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS created_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        ("bookings.updated_by_id", "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS updated_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"),
        ("bookings.customer_id", "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS customer_id VARCHAR(36) REFERENCES customers(id) ON DELETE SET NULL"),
        
        # Customers table
        ("customers.booking_count", "ALTER TABLE customers ADD COLUMN IF NOT EXISTS booking_count INTEGER DEFAULT 0"),
        ("customers.is_banned", "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE"),
        ("customers.ban_reason", "ALTER TABLE customers ADD COLUMN IF NOT EXISTS ban_reason TEXT"),
        ("customers.gender", "ALTER TABLE customers ADD COLUMN IF NOT EXISTS gender VARCHAR(20)"),
    ]
    
    with engine.connect() as conn:
        for name, sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"   ✅ {name}")
            except ProgrammingError as e:
                if "already exists" in str(e) or "duplicate" in str(e).lower():
                    pass  # Column already exists
                else:
                    print(f"   ⚠️  {name}: {e}")
                conn.rollback()
            except Exception as e:
                print(f"   ⚠️  {name}: {e}")
                conn.rollback()
    
    print("✅ Migrations complete!")

