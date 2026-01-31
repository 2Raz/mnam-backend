"""
Database Helper Utilities for Concurrency Control

Provides:
- Database dialect detection (PostgreSQL vs SQLite)
- Atomic locking helpers
- Safe concurrent operations
"""

import logging
from typing import Optional, TypeVar, Type
from sqlalchemy.orm import Session, Query
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

T = TypeVar('T')


def is_postgres(db: Session) -> bool:
    """Check if the database is PostgreSQL"""
    try:
        dialect = db.bind.dialect.name
        return dialect == 'postgresql'
    except Exception:
        return False


def is_sqlite(db: Session) -> bool:
    """Check if the database is SQLite"""
    try:
        dialect = db.bind.dialect.name
        return dialect == 'sqlite'
    except Exception:
        return True  # Default to SQLite for safety


def acquire_row_lock(
    db: Session,
    model: Type[T],
    filter_condition,
    nowait: bool = False,
    skip_locked: bool = False
) -> Optional[T]:
    """
    Acquire a row-level lock on a database record.
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        filter_condition: Filter to find the row
        nowait: If True, raise error immediately if lock unavailable (PostgreSQL only)
        skip_locked: If True, skip locked rows (PostgreSQL only)
    
    Returns:
        The locked model instance, or None if not found
    
    Raises:
        OperationalError: If nowait=True and row is locked by another transaction
    
    Example:
        unit = acquire_row_lock(db, Unit, Unit.id == unit_id, nowait=True)
    """
    query = db.query(model).filter(filter_condition)
    
    # Only apply locking on PostgreSQL
    if is_postgres(db):
        if skip_locked:
            query = query.with_for_update(skip_locked=True)
        elif nowait:
            query = query.with_for_update(nowait=True)
        else:
            query = query.with_for_update()
    
    return query.first()


def acquire_row_lock_or_fail(
    db: Session,
    model: Type[T],
    filter_condition,
    error_message: str = "Resource is locked"
) -> T:
    """
    Acquire a row-level lock or raise HTTPException if unavailable.
    
    Uses nowait=True to fail fast if resource is locked.
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        filter_condition: Filter to find the row
        error_message: Error message if lock fails
    
    Returns:
        The locked model instance
    
    Raises:
        HTTPException 404: If row not found
        HTTPException 409: If row is locked by another transaction
    """
    from fastapi import HTTPException, status
    
    try:
        result = acquire_row_lock(db, model, filter_condition, nowait=True)
    except OperationalError as e:
        # Row is locked by another transaction
        if "could not obtain lock" in str(e).lower() or "lock" in str(e).lower():
            logger.warning(f"Lock contention on {model.__name__}: {e}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_message
            )
        raise
    
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model.__name__} not found"
        )
    
    return result


def get_pending_with_skip_locked(
    db: Session,
    model: Type[T],
    filter_condition,
    order_by=None,
    limit: int = 50
) -> list:
    """
    Get pending records with skip_locked to prevent worker race conditions.
    
    Useful for background workers processing queues.
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        filter_condition: Filter for pending records
        order_by: Optional ordering
        limit: Maximum records to fetch
    
    Returns:
        List of locked model instances (other workers will skip these)
    """
    query = db.query(model).filter(filter_condition)
    
    if order_by is not None:
        query = query.order_by(order_by)
    
    # Only apply skip_locked on PostgreSQL
    if is_postgres(db):
        query = query.with_for_update(skip_locked=True)
    
    return query.limit(limit).all()


class AtomicCounter:
    """
    Helper for atomic counter increments.
    
    Prevents lost updates on concurrent increments.
    
    Example:
        AtomicCounter.increment(db, Customer, Customer.id == customer_id, 'booking_count')
    """
    
    @staticmethod
    def increment(
        db: Session,
        model: Type[T],
        filter_condition,
        column_name: str,
        increment_by: int = 1
    ) -> int:
        """
        Atomically increment a counter column.
        
        Returns the new value after increment.
        """
        from sqlalchemy import update, func
        
        column = getattr(model, column_name)
        
        stmt = (
            update(model)
            .where(filter_condition)
            .values({column_name: func.coalesce(column, 0) + increment_by})
            .returning(column)
        )
        
        if is_postgres(db):
            # PostgreSQL supports RETURNING
            result = db.execute(stmt)
            row = result.fetchone()
            return row[0] if row else 0
        else:
            # SQLite fallback - regular update then select
            db.execute(
                update(model)
                .where(filter_condition)
                .values({column_name: func.coalesce(column, 0) + increment_by})
            )
            record = db.query(model).filter(filter_condition).first()
            return getattr(record, column_name, 0) if record else 0


def safe_upsert_by_unique_key(
    db: Session,
    model: Type[T],
    unique_column: str,
    unique_value,
    create_data: dict,
    update_data: dict
) -> tuple:
    """
    Safely upsert a record by unique key.
    
    Uses locking to prevent duplicate creation.
    
    Args:
        db: Database session
        model: SQLAlchemy model class
        unique_column: Name of the unique column
        unique_value: Value to search for
        create_data: Data for new record creation
        update_data: Data to update if record exists
    
    Returns:
        Tuple of (record, is_new)
    """
    column = getattr(model, unique_column)
    
    # Try to lock existing record
    existing = acquire_row_lock(db, model, column == unique_value)
    
    if existing:
        # Update existing record
        for key, value in update_data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        db.flush()
        return existing, False
    else:
        # Create new record
        new_record = model(**create_data)
        db.add(new_record)
        db.flush()
        return new_record, True
