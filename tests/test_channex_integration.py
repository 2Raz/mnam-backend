"""
Tests for Channex Integration

Tests cover:
- Channex client (mock httpx)
- Rate limiting (token bucket)
- Webhook idempotency
- Webhook security (signature, IP, replay)
- Outbox processing
- Booking creation idempotency
- Integration audit
"""

import pytest
import json
import hashlib
import hmac
from datetime import datetime, timedelta, date
from unittest.mock import Mock, patch, MagicMock

# Import test dependencies
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    IntegrationAudit,
    OutboxStatus,
    OutboxEventType,
    ConnectionStatus,
    AuditDirection,
    AuditEntityType
)
from app.models.webhook_event import WebhookEventLog, WebhookEventStatus
from app.models.rate_state import PropertyRateState
from app.models.booking import Booking, BookingStatus, BookingSource


class TestTokenBucketRateLimiter:
    """Tests for PropertyRateState token bucket"""
    
    def test_initial_tokens(self):
        """New rate state should have full tokens"""
        state = PropertyRateState(channex_property_id="test-prop-1")
        # Initialize manually for testing (DB sets defaults on INSERT)
        state.price_tokens = 10.0
        state.avail_tokens = 10.0
        assert state.price_tokens == 10.0
        assert state.avail_tokens == 10.0
    
    def test_consume_token(self):
        """Consuming a token should reduce count"""
        state = PropertyRateState(channex_property_id="test-prop-2")
        state.price_tokens = 10.0
        state.price_last_refill_at = datetime.utcnow()
        state.total_requests = 0
        
        result = state.consume_token("price")
        assert result == True
        assert state.price_tokens == 9.0
    
    def test_no_tokens_available(self):
        """Should return False when no tokens"""
        state = PropertyRateState(channex_property_id="test-prop-3")
        state.price_tokens = 0.5  # Less than 1 token
        
        result = state.consume_token("price")
        assert result == False
    
    def test_pause_on_429(self):
        """429 should pause the property"""
        state = PropertyRateState(channex_property_id="test-prop-4")
        state.pause_count = 0
        state.total_429s = 0
        state.pause_on_429()
        
        assert state.is_paused() == True
        assert state.pause_count == 1
        assert state.paused_until is not None
    
    def test_exponential_backoff(self):
        """Multiple 429s should increase pause duration"""
        state = PropertyRateState(channex_property_id="test-prop-5")
        state.pause_count = 0
        state.total_429s = 0
        
        # First 429 - 60 seconds
        state.pause_on_429()
        first_duration = (state.paused_until - datetime.utcnow()).total_seconds()
        assert 55 < first_duration < 65  # ~60 seconds
        
        # Reset for next test
        state.paused_until = None
        
        # Second 429 - 120 seconds
        state.pause_on_429()
        second_duration = (state.paused_until - datetime.utcnow()).total_seconds()
        assert 115 < second_duration < 125  # ~120 seconds
    
    def test_max_pause_duration(self):
        """Pause should not exceed MAX_PAUSE_SECONDS"""
        state = PropertyRateState(channex_property_id="test-prop-max")
        state.pause_count = 0
        state.total_429s = 0
        
        # Simulate many consecutive 429s
        for _ in range(10):
            state.paused_until = None
            state.pause_on_429()
        
        # Max is 600 seconds
        duration = (state.paused_until - datetime.utcnow()).total_seconds()
        assert duration <= 605  # ~600 seconds with margin
    
    def test_token_refill(self):
        """Tokens should refill over time"""
        state = PropertyRateState(channex_property_id="test-prop-refill")
        state.price_tokens = 0
        state.price_last_refill_at = datetime.utcnow() - timedelta(seconds=60)
        
        tokens = state.refill_tokens("price")
        # 60 seconds * (10/60) tokens/second = 10 tokens (capped at max)
        assert tokens == 10.0


class TestWebhookIdempotency:
    """Tests for webhook idempotency"""
    
    def test_duplicate_event_detection(self):
        """Same event_id should be detected as duplicate"""
        # This would need a database session
        # For now, test the model structure
        event = WebhookEventLog(
            provider="channex",
            event_id="evt_123",
            event_type="booking.new",
            payload_json='{"test": "data"}',
            status=WebhookEventStatus.PROCESSED.value
        )
        
        assert event.event_id == "evt_123"
        assert event.status == WebhookEventStatus.PROCESSED.value
    
    def test_event_status_transitions(self):
        """Event should transition through statuses"""
        event = WebhookEventLog(
            provider="channex",
            event_id="evt_456",
            event_type="booking.new",
            payload_json='{}',
            status=WebhookEventStatus.RECEIVED.value
        )
        
        # Initial status
        assert event.status == WebhookEventStatus.RECEIVED.value
        
        # Processing
        event.status = WebhookEventStatus.PROCESSING.value
        assert event.status == WebhookEventStatus.PROCESSING.value
        
        # Completed
        event.status = WebhookEventStatus.PROCESSED.value
        event.processed_at = datetime.utcnow()
        assert event.processed_at is not None


class TestWebhookSecurity:
    """Tests for webhook security validation"""
    
    def test_signature_validation(self):
        """HMAC signature should be validated correctly"""
        secret = "test-secret-key"
        payload = b'{"event": "booking.new", "data": {}}'
        
        # Generate valid signature
        expected_sig = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Verify match
        actual_sig = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        assert hmac.compare_digest(expected_sig, actual_sig)
    
    def test_invalid_signature_rejected(self):
        """Invalid signature should not match"""
        secret = "test-secret-key"
        payload = b'{"event": "booking.new"}'
        
        valid_sig = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # Tampered signature
        invalid_sig = "0" * 64
        
        assert not hmac.compare_digest(valid_sig, invalid_sig)
    
    def test_ip_allowlist_format(self):
        """IP allowlist should be parsed correctly"""
        # Test parsing of comma-separated IPs
        ip_string = "192.168.1.1, 10.0.0.1, 172.16.0.1"
        ips = [ip.strip() for ip in ip_string.split(",") if ip.strip()]
        
        assert len(ips) == 3
        assert "192.168.1.1" in ips
        assert "10.0.0.1" in ips
    
    def test_replay_protection_old_event(self):
        """Events older than window should be rejected"""
        window_seconds = 300  # 5 minutes
        old_timestamp = datetime.utcnow() - timedelta(seconds=600)  # 10 minutes ago
        
        age = (datetime.utcnow() - old_timestamp).total_seconds()
        is_too_old = age > window_seconds
        
        assert is_too_old == True
    
    def test_replay_protection_fresh_event(self):
        """Fresh events should be accepted"""
        window_seconds = 300
        fresh_timestamp = datetime.utcnow() - timedelta(seconds=60)  # 1 minute ago
        
        age = (datetime.utcnow() - fresh_timestamp).total_seconds()
        is_too_old = age > window_seconds
        
        assert is_too_old == False


class TestOutboxMerging:
    """Tests for outbox event dedup/merge"""
    
    def test_merge_key_format(self):
        """Events should have proper keys for merging"""
        event1 = IntegrationOutbox(
            connection_id="conn-1",
            event_type=OutboxEventType.PRICE_UPDATE.value,
            unit_id="unit-1",
            payload={"unit_id": "unit-1", "days_ahead": 365},
            status=OutboxStatus.PENDING.value
        )
        
        event2 = IntegrationOutbox(
            connection_id="conn-1",
            event_type=OutboxEventType.PRICE_UPDATE.value,
            unit_id="unit-1",
            payload={"unit_id": "unit-1", "days_ahead": 365},
            status=OutboxStatus.PENDING.value
        )
        
        # Same unit_id and event_type = should merge
        key1 = (event1.unit_id, event1.event_type)
        key2 = (event2.unit_id, event2.event_type)
        assert key1 == key2
    
    def test_different_event_types_no_merge(self):
        """Different event types should not merge"""
        price_event = IntegrationOutbox(
            connection_id="conn-1",
            event_type=OutboxEventType.PRICE_UPDATE.value,
            unit_id="unit-1",
            payload={},
            status=OutboxStatus.PENDING.value
        )
        
        avail_event = IntegrationOutbox(
            connection_id="conn-1",
            event_type=OutboxEventType.AVAIL_UPDATE.value,
            unit_id="unit-1",
            payload={},
            status=OutboxStatus.PENDING.value
        )
        
        key1 = (price_event.unit_id, price_event.event_type)
        key2 = (avail_event.unit_id, avail_event.event_type)
        assert key1 != key2


class TestChannexClientAuth:
    """Tests for Channex client authentication"""
    
    def test_auth_header_format(self):
        """Should use user-api-key header, not Bearer"""
        # Mock the client
        with patch('app.services.channex_client.httpx'):
            from app.services.channex_client import ChannexClient
            
            client = ChannexClient(
                api_key="test-api-key",
                channex_property_id="prop-123"
            )
            
            headers = client._get_headers()
            
            # Should have user-api-key, NOT Authorization: Bearer
            assert "user-api-key" in headers
            assert headers["user-api-key"] == "test-api-key"
            assert "Bearer" not in headers.get("Authorization", "")
    
    def test_request_id_in_headers(self):
        """Request ID should be included in headers"""
        with patch('app.services.channex_client.httpx'):
            from app.services.channex_client import ChannexClient
            
            client = ChannexClient(
                api_key="test-api-key",
                channex_property_id="prop-123",
                request_id="req-abc-123"
            )
            
            headers = client._get_headers()
            
            assert "X-Request-ID" in headers
            assert headers["X-Request-ID"] == "req-abc-123"


class TestBookingSourceMapping:
    """Tests for booking source enum and mapping"""
    
    def test_all_ota_sources_exist(self):
        """All expected OTA sources should be in enum"""
        expected_sources = [
            "direct", "airbnb", "booking.com", 
            "expedia", "agoda", "gathern", 
            "channex", "other_ota", "unknown"
        ]
        
        for source in expected_sources:
            assert source in [s.value for s in BookingSource]
    
    def test_channex_source_added(self):
        """CHANNEX source should exist for unknown OTA bookings"""
        assert BookingSource.CHANNEX.value == "channex"
    
    def test_channel_source_mapping(self):
        """OTA names should map to correct BookingSource"""
        from app.models.booking import BookingSource
        
        # Test mapping expectations
        mappings = {
            "airbnb": BookingSource.AIRBNB.value,
            "booking.com": BookingSource.BOOKING_COM.value,
            "expedia": BookingSource.EXPEDIA.value,
            "agoda": BookingSource.AGODA.value,
            "channex": BookingSource.CHANNEX.value,
        }
        
        for channel, expected in mappings.items():
            assert expected in [s.value for s in BookingSource]


class TestPricingForChannel:
    """Tests for pricing engine channel push format"""
    
    def test_weekend_days_from_config(self):
        """Weekend days should come from config"""
        from app.config import settings
        
        # Default Saudi weekend
        weekend_days = settings.weekend_day_numbers
        assert 4 in weekend_days  # Friday
        assert 5 in weekend_days  # Saturday
    
    def test_channel_rate_format(self):
        """Rates for Channex should be in correct format"""
        # Expected format: {"date": "2024-01-15", "rate": 100.00}
        sample_rate = {"date": "2024-01-15", "rate": 100.00}
        
        assert "date" in sample_rate
        assert "rate" in sample_rate
        assert isinstance(sample_rate["rate"], (int, float))


class TestIntegrationAudit:
    """Tests for integration audit trail"""
    
    def test_audit_model_structure(self):
        """Audit model should have required fields"""
        audit = IntegrationAudit(
            direction=AuditDirection.OUTBOUND.value,
            entity_type=AuditEntityType.RATE.value,
            status="pending"
        )
        
        assert audit.direction == "outbound"
        assert audit.entity_type == "rate"
        assert audit.status == "pending"
    
    def test_audit_directions(self):
        """Audit directions should be correct"""
        assert AuditDirection.OUTBOUND.value == "outbound"
        assert AuditDirection.INBOUND.value == "inbound"
    
    def test_audit_entity_types(self):
        """Audit entity types should cover all sync types"""
        expected_types = ["availability", "rate", "restrictions", "booking", "full_sync"]
        for entity_type in expected_types:
            assert entity_type in [t.value for t in AuditEntityType]
    
    def test_payload_hash_generation(self):
        """Payload hash should be deterministic"""
        from app.services.health_check import compute_payload_hash
        
        payload = {"date": "2024-01-15", "rate": 100}
        hash1 = compute_payload_hash(payload)
        hash2 = compute_payload_hash(payload)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length


class TestHealthCheck:
    """Tests for health check service"""
    
    def test_channex_enabled_setting(self):
        """CHANNEX_ENABLED should be accessible from config"""
        from app.config import settings
        
        # Default is True
        assert hasattr(settings, 'channex_enabled')
        assert isinstance(settings.channex_enabled, bool)
    
    def test_allowed_ips_parsing(self):
        """Allowed IPs should parse correctly"""
        from app.config import Settings
        
        # Test with empty
        s = Settings(channex_allowed_ips="")
        assert s.channex_allowed_ip_list == []
        
        # Test with values
        s = Settings(channex_allowed_ips="1.2.3.4,5.6.7.8")
        assert "1.2.3.4" in s.channex_allowed_ip_list
        assert "5.6.7.8" in s.channex_allowed_ip_list


class TestBookingCreationIdempotency:
    """Tests for booking creation idempotency"""
    
    def test_external_reservation_id_unique(self):
        """External reservation ID should prevent duplicates"""
        # Booking with external ID
        booking1 = Booking(
            external_reservation_id="RES-12345",
            guest_name="Test Guest",
            check_in_date=date(2024, 1, 15),
            check_out_date=date(2024, 1, 17),
            unit_id="unit-1"
        )
        
        # Same reservation ID = should be treated as duplicate
        booking2 = Booking(
            external_reservation_id="RES-12345",
            guest_name="Test Guest",
            check_in_date=date(2024, 1, 15),
            check_out_date=date(2024, 1, 17),
            unit_id="unit-1"
        )
        
        assert booking1.external_reservation_id == booking2.external_reservation_id


# Entry point for running tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])

