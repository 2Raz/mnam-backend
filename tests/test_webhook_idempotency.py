"""
Tests for Webhook Idempotency

Tests cover:
- Duplicate delivery handling
- Update before create (upsert)
- Cancel unknown booking handling
- Mapping fallback to rate_plan_id
- Unmatched event persistence
- External reservation uniqueness

Per /chandoc Section 7 & 8:
- Webhooks MUST be idempotent
- Webhooks MUST NOT drop events silently
"""

import pytest
import json
from datetime import datetime, date
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import asdict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestWebhookIdempotency:
    """Tests for webhook idempotency requirements"""
    
    def test_webhook_idempotent_duplicate_delivery(self):
        """Same webhook delivered twice should not create duplicate bookings"""
        from app.services.webhook_processor import WebhookProcessor, WebhookProcessResult
        
        # Mock DB session
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        # Create mock event
        event = MagicMock()
        event.id = "event-1"
        event.event_id = "channex-event-123"
        event.payload = {
            "event": "booking_new",
            "property_id": "prop-1",
            "data": {
                "id": "res-123",
                "room_type_id": "rt-1",
                "guest": {"name": "Test Guest"},
                "arrival_date": "2024-01-15",
                "departure_date": "2024-01-17"
            }
        }
        
        # Mock connection
        connection = MagicMock()
        connection.id = "conn-1"
        connection.channex_property_id = "prop-1"
        processor._find_connection_by_property = MagicMock(return_value=connection)
        
        # Mock mapping
        processor._find_unit_by_room_type = MagicMock(return_value="unit-1")
        
        # First call: no existing booking
        existing_booking = MagicMock()
        existing_booking.id = "book-1"
        
        # Mock query to return existing booking (already created)
        query_mock = MagicMock()
        query_mock.filter.return_value.with_for_update.return_value.first.return_value = existing_booking
        db.query.return_value = query_mock
        
        # Process duplicate
        result = processor._handle_booking_new(event.payload, event)
        
        # Should skip, not create duplicate
        assert result.success == True
        assert result.action == "skipped"
        assert result.booking_id == "book-1"
    
    def test_webhook_update_before_create_upsert(self):
        """Modified event for non-existent booking should create it (upsert)"""
        from app.services.webhook_processor import WebhookProcessor
        
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        event = MagicMock()
        event.id = "event-2"
        event.event_id = "channex-event-456"
        event.payload = {
            "event": "booking_modified",
            "property_id": "prop-1",
            "data": {
                "id": "res-456",
                "room_type_id": "rt-1",
                "guest": {"name": "Updated Guest"},
                "arrival_date": "2024-02-01",
                "departure_date": "2024-02-03",
                "status": "confirmed"
            }
        }
        
        connection = MagicMock()
        connection.id = "conn-1"
        connection.channex_property_id = "prop-1"
        processor._find_connection_by_property = MagicMock(return_value=connection)
        processor._find_unit_by_room_type = MagicMock(return_value="unit-1")
        
        # No existing booking - should trigger upsert (create)
        query_mock = MagicMock()
        query_mock.filter.return_value.with_for_update.return_value.first.return_value = None
        db.query.return_value = query_mock
        
        # Mock _handle_booking_new to verify it gets called
        processor._handle_booking_new = MagicMock(return_value=MagicMock(success=True, action="created"))
        
        result = processor._handle_booking_modified(event.payload, event)
        
        # Should have called _handle_booking_new (upsert)
        processor._handle_booking_new.assert_called_once()
    
    def test_webhook_cancel_unknown_booking_no_crash(self):
        """Cancel event for unknown booking should not crash"""
        from app.services.webhook_processor import WebhookProcessor
        from app.models.webhook_event import WebhookEventLog
        
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        event = MagicMock()
        event.id = "event-3"
        event.event_id = "channex-event-789"
        event.payload = {
            "event": "booking_cancelled",
            "property_id": "prop-1",
            "data": {
                "id": "res-unknown",
                "status": "cancelled"
            }
        }
        
        # No existing booking
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = None
        db.query.return_value = query_mock
        
        # Mock idempotency recording
        processor._record_idempotency = MagicMock()
        
        result = processor._handle_booking_cancelled(event.payload, event)
        
        # Should succeed with not_found action, no crash
        assert result.success == True
        assert result.action == "not_found"
    
    def test_webhook_mapping_fallback_rate_plan(self):
        """If room_type_id fails, should try rate_plan_id fallback"""
        from app.services.webhook_processor import WebhookProcessor
        
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        event = MagicMock()
        event.id = "event-4"
        event.event_id = "channex-event-fallback"
        event.payload = {
            "event": "booking_new",
            "property_id": "prop-1",
            "data": {
                "id": "res-fallback",
                "room_type_id": "unknown-rt",
                "rate_plan_id": "rp-1",
                "guest": {"name": "Fallback Guest"},
                "arrival_date": "2024-03-01",
                "departure_date": "2024-03-03"
            }
        }
        
        connection = MagicMock()
        connection.id = "conn-1"
        connection.channex_property_id = "prop-1"
        processor._find_connection_by_property = MagicMock(return_value=connection)
        
        # room_type_id lookup fails
        processor._find_unit_by_room_type = MagicMock(return_value=None)
        
        # rate_plan_id fallback succeeds
        processor._find_unit_by_rate_plan = MagicMock(return_value="unit-fallback")
        
        # No existing booking
        query_mock = MagicMock()
        query_mock.filter.return_value.with_for_update.return_value.first.return_value = None
        db.query.return_value = query_mock
        
        processor._find_or_create_customer = MagicMock(return_value=MagicMock(id="cust-1"))
        processor._record_idempotency = MagicMock()
        processor._queue_availability_update = MagicMock()
        
        result = processor._handle_booking_new(event.payload, event)
        
        # Should have used fallback
        processor._find_unit_by_rate_plan.assert_called_once_with("conn-1", "rp-1")
    
    def test_webhook_unmatched_event_persisted(self):
        """Unresolvable webhook should be saved to unmatched events table"""
        from app.services.webhook_processor import WebhookProcessor
        from app.models.unmatched_webhook import UnmatchedEventReason
        
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        event = MagicMock()
        event.id = "event-5"
        event.event_id = "channex-event-unmatched"
        event.payload = {
            "event": "booking_new",
            "property_id": "prop-1",
            "data": {
                "id": "res-unmatched",
                "room_type_id": "unknown-rt",
                "rate_plan_id": "unknown-rp",
                "guest": {"name": "Unmatched Guest"},
                "arrival_date": "2024-04-01",
                "departure_date": "2024-04-03"
            }
        }
        
        connection = MagicMock()
        connection.id = "conn-1"
        connection.channex_property_id = "prop-1"
        processor._find_connection_by_property = MagicMock(return_value=connection)
        
        # Both lookups fail
        processor._find_unit_by_room_type = MagicMock(return_value=None)
        processor._find_unit_by_rate_plan = MagicMock(return_value=None)
        
        # Mock _save_unmatched_event
        processor._save_unmatched_event = MagicMock()
        
        result = processor._handle_booking_new(event.payload, event)
        
        # Should have saved unmatched event
        processor._save_unmatched_event.assert_called_once()
        call_args = processor._save_unmatched_event.call_args
        assert call_args.kwargs["reason"] == UnmatchedEventReason.NO_MAPPING.value
        
        # Should return success to prevent webhook retries
        assert result.success == True
        assert result.action == "unmatched"
    
    def test_booking_unique_external_reservation_constraint(self):
        """Verify booking model has external_reservation_id field"""
        from app.models.booking import Booking
        
        # Verify field exists
        assert hasattr(Booking, 'external_reservation_id')
        assert hasattr(Booking, 'source_type')
        assert hasattr(Booking, 'channel_source')


class TestUnmatchedWebhookEvent:
    """Tests for UnmatchedWebhookEvent model"""
    
    def test_model_fields_exist(self):
        """Verify all required fields exist on model"""
        from app.models.unmatched_webhook import UnmatchedWebhookEvent, UnmatchedEventStatus, UnmatchedEventReason
        
        # Verify fields
        assert hasattr(UnmatchedWebhookEvent, 'id')
        assert hasattr(UnmatchedWebhookEvent, 'provider')
        assert hasattr(UnmatchedWebhookEvent, 'event_type')
        assert hasattr(UnmatchedWebhookEvent, 'external_reservation_id')
        assert hasattr(UnmatchedWebhookEvent, 'raw_payload')
        assert hasattr(UnmatchedWebhookEvent, 'reason')
        assert hasattr(UnmatchedWebhookEvent, 'status')
        assert hasattr(UnmatchedWebhookEvent, 'retry_count')
        
        # Verify enums
        assert UnmatchedEventStatus.PENDING.value == "pending"
        assert UnmatchedEventStatus.RESOLVED.value == "resolved"
        assert UnmatchedEventStatus.IGNORED.value == "ignored"
        
        assert UnmatchedEventReason.NO_MAPPING.value == "no_mapping"
        assert UnmatchedEventReason.NO_CONNECTION.value == "no_connection"


class TestConcurrencySafety:
    """Tests for concurrency safety in webhook processing"""
    
    def test_booking_query_uses_for_update(self):
        """Verify booking queries use FOR UPDATE lock"""
        from app.services.webhook_processor import WebhookProcessor
        
        db = MagicMock()
        processor = WebhookProcessor(db)
        
        event = MagicMock()
        event.payload = {
            "event": "booking_modified",
            "property_id": "prop-1",
            "data": {
                "id": "res-lock-test",
                "status": "confirmed"
            }
        }
        
        # Mock connection
        connection = MagicMock()
        connection.id = "conn-1"
        processor._find_connection_by_property = MagicMock(return_value=connection)
        
        # Setup query mock chain
        query_mock = MagicMock()
        filter_mock = MagicMock()
        for_update_mock = MagicMock()
        
        query_mock.filter.return_value = filter_mock
        filter_mock.with_for_update.return_value = for_update_mock
        for_update_mock.first.return_value = None  # No booking found
        
        db.query.return_value = query_mock
        
        # Mock _handle_booking_new for the upsert case
        processor._handle_booking_new = MagicMock(return_value=MagicMock(success=True))
        
        processor._handle_booking_modified(event.payload, event)
        
        # Verify with_for_update was called
        filter_mock.with_for_update.assert_called_once()
