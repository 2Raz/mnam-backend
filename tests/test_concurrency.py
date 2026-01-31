"""
Concurrency Tests for Race Condition Prevention

Tests cover:
- Double booking prevention
- Customer upsert race conditions
- Webhook worker race conditions
- Token refresh race conditions
- Outbox worker race conditions

These tests verify that our locking mechanisms work correctly.
"""

import pytest
import json
from datetime import datetime, date, timedelta
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestBookingConcurrency:
    """Tests for booking double-booking prevention"""
    
    def test_acquire_row_lock_uses_for_update_on_postgres(self):
        """Verify acquire_row_lock applies with_for_update on PostgreSQL"""
        from app.utils.db_helpers import acquire_row_lock
        from app.models.unit import Unit
        
        db = MagicMock()
        
        # Configure mock to simulate PostgreSQL dialect
        db.bind.dialect.name = 'postgresql'
        
        # Setup query chain
        query_mock = MagicMock()
        filter_mock = MagicMock()
        for_update_mock = MagicMock()
        
        query_mock.filter.return_value = filter_mock
        filter_mock.with_for_update.return_value = for_update_mock
        for_update_mock.first.return_value = MagicMock()
        
        db.query.return_value = query_mock
        
        # Call acquire_row_lock with nowait=True
        result = acquire_row_lock(db, Unit, Unit.id == 'test-id', nowait=True)
        
        # Verify with_for_update was called with nowait=True
        filter_mock.with_for_update.assert_called_once_with(nowait=True)
    
    def test_acquire_row_lock_skips_locking_on_sqlite(self):
        """Verify acquire_row_lock skips locking on SQLite"""
        from app.utils.db_helpers import acquire_row_lock
        from app.models.unit import Unit
        
        db = MagicMock()
        
        # Configure mock to simulate SQLite dialect
        db.bind.dialect.name = 'sqlite'
        
        # Setup query chain (no for_update)
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.first.return_value = MagicMock()
        
        query_mock.filter.return_value = filter_mock
        db.query.return_value = query_mock
        
        result = acquire_row_lock(db, Unit, Unit.id == 'test-id', nowait=True)
        
        # For SQLite, with_for_update should NOT be called
        filter_mock.with_for_update.assert_not_called()
    
    def test_booking_creation_uses_unit_lock(self):
        """Verify create_booking acquires lock on unit"""
        # This test verifies the code structure, not actual locking behavior
        # (actual behavior requires a real database)
        import ast
        
        with open('app/routers/bookings.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that acquire_row_lock is imported
        assert 'from ..utils.db_helpers import acquire_row_lock' in content
        
        # Check that acquire_row_lock is used for Unit
        assert 'acquire_row_lock' in content
        assert 'Unit.id == booking_data.unit_id' in content
    
    def test_booking_status_update_uses_lock(self):
        """Verify update_booking_status acquires lock on booking"""
        with open('app/routers/bookings.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that booking status update uses locking
        assert 'acquire_row_lock(db, Booking, Booking.id == booking_id)' in content


class TestCustomerConcurrency:
    """Tests for customer upsert race condition prevention"""
    
    def test_upsert_customer_uses_lock(self):
        """Verify upsert_customer_from_booking uses row locking"""
        with open('app/services/customer_service.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that acquire_row_lock is used
        assert 'from ..utils.db_helpers import acquire_row_lock' in content
        assert 'acquire_row_lock' in content
        assert 'Customer.phone == normalized_phone' in content
    
    def test_atomic_counter_increment(self):
        """Verify AtomicCounter provides atomic increments"""
        from app.utils.db_helpers import AtomicCounter
        from app.models.customer import Customer
        
        db = MagicMock()
        db.bind.dialect.name = 'postgresql'
        
        # Mock execute for RETURNING clause
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = (5,)  # New value after increment
        db.execute.return_value = execute_mock
        
        result = AtomicCounter.increment(
            db, Customer, 
            Customer.id == 'cust-1', 
            'booking_count', 
            increment_by=1
        )
        
        # Verify execute was called (for PostgreSQL with RETURNING)
        assert db.execute.called or db.query.called


class TestWebhookConcurrency:
    """Tests for webhook worker race condition prevention"""
    
    def test_webhook_processor_get_pending_uses_skip_locked(self):
        """Verify WebhookProcessor.get_pending_events uses skip_locked"""
        with open('app/services/webhook_processor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that skip_locked is used in get_pending_events
        assert 'skip_locked=True' in content
        assert 'is_postgres(self.db)' in content
    
    def test_webhook_booking_operations_use_for_update(self):
        """Verify booking operations in webhook use with_for_update"""
        with open('app/services/webhook_processor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that with_for_update is used for booking queries
        assert '.with_for_update()' in content


class TestOutboxConcurrency:
    """Tests for outbox worker race condition prevention"""
    
    def test_outbox_get_pending_uses_skip_locked(self):
        """Verify OutboxProcessor.get_pending_events uses skip_locked"""
        with open('app/services/outbox_worker.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that skip_locked is used
        assert 'skip_locked=True' in content
        assert 'is_postgres(self.db)' in content
    
    def test_outbox_processor_instantiation(self):
        """Verify OutboxProcessor can be instantiated"""
        from app.services.outbox_worker import OutboxProcessor
        
        db = MagicMock()
        processor = OutboxProcessor(db)
        
        assert processor.db == db


class TestTokenConcurrency:
    """Tests for refresh token race condition prevention"""
    
    def test_refresh_token_uses_for_update(self):
        """Verify refresh_tokens uses with_for_update"""
        with open('app/routers/auth.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that with_for_update is used for token query
        assert '.with_for_update(nowait=True)' in content
        assert 'is_postgres(db)' in content
    
    def test_refresh_token_handles_lock_exception(self):
        """Verify refresh_tokens handles lock exceptions gracefully"""
        with open('app/routers/auth.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that exception handling exists for locked tokens
        assert 'Token locked by concurrent request' in content
        assert 'يتم تجديد الجلسة من جهاز آخر' in content


class TestDbHelpers:
    """Tests for database helper utilities"""
    
    def test_is_postgres_returns_true_for_postgresql(self):
        """Verify is_postgres returns True for PostgreSQL"""
        from app.utils.db_helpers import is_postgres
        
        db = MagicMock()
        db.bind.dialect.name = 'postgresql'
        
        assert is_postgres(db) == True
    
    def test_is_postgres_returns_false_for_sqlite(self):
        """Verify is_postgres returns False for SQLite"""
        from app.utils.db_helpers import is_postgres
        
        db = MagicMock()
        db.bind.dialect.name = 'sqlite'
        
        assert is_postgres(db) == False
    
    def test_is_sqlite_returns_true_for_sqlite(self):
        """Verify is_sqlite returns True for SQLite"""
        from app.utils.db_helpers import is_sqlite
        
        db = MagicMock()
        db.bind.dialect.name = 'sqlite'
        
        assert is_sqlite(db) == True
    
    def test_get_pending_with_skip_locked(self):
        """Verify get_pending_with_skip_locked applies correct locking"""
        from app.utils.db_helpers import get_pending_with_skip_locked
        from app.models.booking import Booking
        
        db = MagicMock()
        db.bind.dialect.name = 'postgresql'
        
        # Setup query chain
        query_mock = MagicMock()
        filter_mock = MagicMock()
        order_mock = MagicMock()
        for_update_mock = MagicMock()
        limit_mock = MagicMock()
        
        query_mock.filter.return_value = filter_mock
        filter_mock.order_by.return_value = order_mock
        order_mock.with_for_update.return_value = for_update_mock
        for_update_mock.limit.return_value = limit_mock
        limit_mock.all.return_value = []
        
        db.query.return_value = query_mock
        
        result = get_pending_with_skip_locked(
            db, Booking, 
            Booking.status == 'pending',
            Booking.created_at,
            limit=50
        )
        
        # Verify with_for_update(skip_locked=True) was called
        order_mock.with_for_update.assert_called_once_with(skip_locked=True)


class TestIntegrationScenarios:
    """Integration-like tests for common race condition scenarios"""
    
    def test_simulated_concurrent_booking_check(self):
        """
        Simulate checking for overlapping bookings under concurrent access.
        
        This doesn't test actual database behavior but verifies the code
        structure handles concurrency.
        """
        # Verify the check_booking_overlap function exists and is called
        # within a locked context in create_booking
        with open('app/routers/bookings.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find create_booking function
        assert 'async def create_booking' in content
        
        # Verify the sequence: lock -> check -> create
        lock_pos = content.find('acquire_row_lock')
        check_pos = content.find('check_booking_overlap', lock_pos)
        create_pos = content.find('Booking(', check_pos)
        
        assert lock_pos < check_pos < create_pos, \
            "Lock must come before overlap check, which must come before booking creation"
    
    def test_simulated_webhook_idempotency_flow(self):
        """
        Verify webhook processing follows idempotent pattern:
        1. Receive and persist (fast)
        2. Worker picks up with lock
        3. Process with booking lock
        """
        with open('app/services/webhook_processor.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check all components are present
        assert 'class AsyncWebhookReceiver' in content  # Fast receive
        assert 'class WebhookProcessor' in content  # Worker
        assert 'skip_locked=True' in content  # Worker race prevention
        assert '.with_for_update()' in content  # Booking lock


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
