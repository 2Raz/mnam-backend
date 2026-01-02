import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Get database URL directly from environment variable
# Railway sets DATABASE_URL automatically when you add PostgreSQL
database_url = os.environ.get("DATABASE_URL", "sqlite:///./mnam.db")

# Print for debugging (remove in production)
print(f"🔗 Database URL prefix: {database_url[:30]}...")

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
    echo=not is_production,  # Disable SQL logging in production
    pool_pre_ping=True,  # Test connection before using
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
