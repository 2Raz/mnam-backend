"""
Alembic Environment Configuration for mnam-backend

This file configures Alembic to:
- Read DATABASE_URL from environment variables (Railway compatible)
- Use SQLAlchemy 2.0 with async support ready
- Auto-detect model changes for migrations
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import create_engine

from alembic import context

# Add the app directory to the path so we can import our models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our Base and all models for autogenerate
from app.database import Base
from app.models import (
    User, Owner, Project, Unit, Booking, Transaction, Customer,
    RefreshToken, EmployeeActivityLog, EmployeeTarget, EmployeePerformanceSummary
)

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object for autogenerate support
target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Get DATABASE_URL from environment variables.
    Handles Railway's various formats including:
    - DATABASE_URL directly
    - PG* variables (PGHOST, PGPORT, etc.)
    - postgres:// -> postgresql:// conversion
    """
    database_url = os.environ.get("DATABASE_URL")
    
    # If no DATABASE_URL, try Railway's PG* variables
    if not database_url:
        pg_host = os.environ.get("PGHOST")
        pg_port = os.environ.get("PGPORT", "5432")
        pg_user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER")
        pg_password = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD")
        pg_database = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB")
        
        if pg_host and pg_user and pg_password and pg_database:
            database_url = f"postgresql://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
        else:
            # Fallback for local development - use SQLite
            database_url = "sqlite:///./mnam.db"
    
    # Railway provides postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    return database_url


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.
    
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    
    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    url = get_database_url()
    
    # Handle SQLite check_same_thread
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    
    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
        future=True,  # SQLAlchemy 2.0 mode
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # Important: These settings help with safe migrations
            render_as_batch=url.startswith("sqlite"),  # Batch mode for SQLite
            include_schemas=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
