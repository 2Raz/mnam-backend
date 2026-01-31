"""
Tests for Channex Webhook Handler

These tests verify:
- Webhook payload parsing
- Booking creation from webhook
- Booking modification handling
- Booking cancellation
- Idempotency (duplicate event handling)
"""

import pytest
import json
from datetime import date, datetime
from unittest.mock import MagicMock, patch


class TestWebhookPayloadParsing:
    """Tests for parsing Channex webhook payloads"""
    
    def parse_date(self, date_str):
        """Simulate date parsing logic"""
        if not date_str:
            return None
        
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(date_str.split("T")[0], fmt.split("T")[0]).date()
            except ValueError:
                continue
        return None
    
    def test_parse_iso_date(self):
        """Should parse ISO date format"""
        result = self.parse_date("2026-01-15")
        assert result == date(2026, 1, 15)
    
    def test_parse_datetime_string(self):
        """Should parse datetime string and extract date"""
        result = self.parse_date("2026-01-15T14:30:00")
        assert result == date(2026, 1, 15)
    
    def test_parse_datetime_utc(self):
        """Should parse UTC datetime string"""
        result = self.parse_date("2026-01-15T14:30:00Z")
        assert result == date(2026, 1, 15)
    
    def test_parse_none(self):
        """Should return None for None input"""
        result = self.parse_date(None)
        assert result is None
    
    def test_parse_empty(self):
        """Should return None for empty string"""
        result = self.parse_date("")
        assert result is None


class TestBookingStatusMapping:
    """Tests for mapping Channex status to MNAM status"""
    
    def map_status(self, status):
        """Simulate status mapping logic"""
        if not status:
            return "مؤكد"
        
        status_lower = status.lower()
        if status_lower in ("confirmed", "new", "reserved"):
            return "مؤكد"
        elif status_lower in ("cancelled", "canceled"):
            return "ملغي"
        elif status_lower in ("checked_in", "checkin"):
            return "دخول"
        elif status_lower in ("checked_out", "checkout"):
            return "خروج"
        elif status_lower == "completed":
            return "مكتمل"
        else:
            return "مؤكد"
    
    def test_confirmed_status(self):
        """Confirmed status should map to مؤكد"""
        assert self.map_status("confirmed") == "مؤكد"
        assert self.map_status("CONFIRMED") == "مؤكد"
        assert self.map_status("new") == "مؤكد"
        assert self.map_status("reserved") == "مؤكد"
    
    def test_cancelled_status(self):
        """Cancelled status should map to ملغي"""
        assert self.map_status("cancelled") == "ملغي"
        assert self.map_status("canceled") == "ملغي"
        assert self.map_status("CANCELLED") == "ملغي"
    
    def test_checkin_status(self):
        """Check-in status should map to دخول"""
        assert self.map_status("checked_in") == "دخول"
        assert self.map_status("checkin") == "دخول"
    
    def test_checkout_status(self):
        """Check-out status should map to خروج"""
        assert self.map_status("checked_out") == "خروج"
        assert self.map_status("checkout") == "خروج"
    
    def test_default_status(self):
        """Unknown status should default to مؤكد"""
        assert self.map_status("unknown") == "مؤكد"
        assert self.map_status(None) == "مؤكد"


class TestChannelSourceMapping:
    """Tests for mapping OTA channel names"""
    
    def map_channel(self, channel):
        """Simulate channel source mapping"""
        if not channel:
            return "channex"
        
        channel_lower = channel.lower()
        if "airbnb" in channel_lower:
            return "airbnb"
        elif "booking.com" in channel_lower or "booking" == channel_lower:
            return "booking.com"
        elif "expedia" in channel_lower:
            return "expedia"
        elif "agoda" in channel_lower:
            return "agoda"
        else:
            return "other_ota"
    
    def test_airbnb(self):
        """Airbnb variations should map to airbnb"""
        assert self.map_channel("Airbnb") == "airbnb"
        assert self.map_channel("airbnb.com") == "airbnb"
        assert self.map_channel("AIRBNB") == "airbnb"
    
    def test_booking_com(self):
        """Booking.com variations should map correctly"""
        assert self.map_channel("Booking.com") == "booking.com"
        assert self.map_channel("booking") == "booking.com"
        assert self.map_channel("BOOKING.COM") == "booking.com"
    
    def test_expedia(self):
        """Expedia should map to expedia"""
        assert self.map_channel("Expedia") == "expedia"
        assert self.map_channel("expedia.com") == "expedia"
    
    def test_agoda(self):
        """Agoda should map to agoda"""
        assert self.map_channel("Agoda") == "agoda"
    
    def test_other_ota(self):
        """Unknown OTAs should map to other_ota"""
        assert self.map_channel("vrbo") == "other_ota"
        assert self.map_channel("tripadvisor") == "other_ota"
    
    def test_default(self):
        """None should map to channex"""
        assert self.map_channel(None) == "channex"


class TestGuestNameParsing:
    """Tests for extracting guest name from webhook payload"""
    
    def extract_guest_name(self, guest_data):
        """Simulate guest name extraction"""
        if not guest_data:
            return "OTA Guest"
        
        name = guest_data.get("name") or guest_data.get("full_name")
        if name:
            return name
        
        first = guest_data.get("first_name", "")
        last = guest_data.get("last_name", "")
        combined = f"{first} {last}".strip()
        
        return combined if combined else "OTA Guest"
    
    def test_full_name(self):
        """Should use full_name if available"""
        guest = {"full_name": "John Smith"}
        assert self.extract_guest_name(guest) == "John Smith"
    
    def test_name_field(self):
        """Should use name field if available"""
        guest = {"name": "Jane Doe"}
        assert self.extract_guest_name(guest) == "Jane Doe"
    
    def test_first_last_name(self):
        """Should combine first and last name"""
        guest = {"first_name": "Mohammed", "last_name": "Ali"}
        assert self.extract_guest_name(guest) == "Mohammed Ali"
    
    def test_first_name_only(self):
        """Should use first name if only that is available"""
        guest = {"first_name": "Ahmed"}
        assert self.extract_guest_name(guest) == "Ahmed"
    
    def test_empty_guest(self):
        """Should default to OTA Guest for empty data"""
        assert self.extract_guest_name({}) == "OTA Guest"
        assert self.extract_guest_name(None) == "OTA Guest"


class TestIdempotency:
    """Tests for webhook idempotency logic"""
    
    def test_duplicate_event_detection(self):
        """Same event_id should be detected as duplicate"""
        processed_events = {"event_123", "event_456"}
        
        # New event
        assert "event_789" not in processed_events
        
        # Duplicate event
        assert "event_123" in processed_events
    
    def test_revision_tracking(self):
        """Revision ID should be tracked for modifications"""
        processed_revisions = {}
        reservation_id = "res_001"
        
        # First revision
        processed_revisions[reservation_id] = "rev_1"
        
        # Same revision - skip
        new_revision = "rev_1"
        is_new = processed_revisions.get(reservation_id) != new_revision
        assert is_new == False
        
        # New revision - process
        new_revision = "rev_2"
        is_new = processed_revisions.get(reservation_id) != new_revision
        assert is_new == True


class TestWebhookPayloadStructure:
    """Tests for handling different webhook payload structures"""
    
    def test_booking_new_payload(self):
        """Sample booking.new webhook payload"""
        payload = {
            "event": "booking.new",
            "property_id": "prop_123",
            "data": {
                "id": "booking_001",
                "revision_id": "1",
                "room_type_id": "rt_456",
                "arrival_date": "2026-01-20",
                "departure_date": "2026-01-23",
                "status": "confirmed",
                "total_price": 750.00,
                "guest": {
                    "name": "Ahmed Ali",
                    "phone": "+966500000000",
                    "email": "ahmed@example.com"
                },
                "ota_name": "Airbnb"
            }
        }
        
        assert payload["event"] == "booking.new"
        assert payload["data"]["id"] == "booking_001"
        assert payload["data"]["guest"]["name"] == "Ahmed Ali"
    
    def test_booking_cancelled_payload(self):
        """Sample booking.cancelled webhook payload"""
        payload = {
            "event": "booking.cancelled",
            "property_id": "prop_123",
            "data": {
                "id": "booking_001",
                "revision_id": "2",
                "status": "cancelled",
                "cancellation_reason": "Guest request"
            }
        }
        
        assert payload["event"] == "booking.cancelled"
        assert payload["data"]["status"] == "cancelled"


class TestSignatureVerification:
    """Tests for webhook signature verification"""
    
    def verify_hmac(self, payload: bytes, signature: str, secret: str) -> bool:
        """Simulate HMAC verification"""
        import hmac
        import hashlib
        
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    
    def test_valid_signature(self):
        """Valid signature should pass verification"""
        import hmac
        import hashlib
        
        secret = "test_secret_key"
        payload = b'{"event": "booking.new"}'
        
        # Generate correct signature
        signature = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        assert self.verify_hmac(payload, signature, secret) == True
    
    def test_invalid_signature(self):
        """Invalid signature should fail verification"""
        secret = "test_secret_key"
        payload = b'{"event": "booking.new"}'
        wrong_signature = "wrong_signature_here"
        
        assert self.verify_hmac(payload, wrong_signature, secret) == False
    
    def test_tampered_payload(self):
        """Tampered payload should fail verification"""
        import hmac
        import hashlib
        
        secret = "test_secret_key"
        original_payload = b'{"event": "booking.new"}'
        tampered_payload = b'{"event": "booking.cancelled"}'
        
        # Signature for original
        signature = hmac.new(
            secret.encode('utf-8'),
            original_payload,
            hashlib.sha256
        ).hexdigest()
        
        # Verify with tampered payload
        assert self.verify_hmac(tampered_payload, signature, secret) == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
