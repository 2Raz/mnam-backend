"""
Unmatched Webhook Event Model

Stores webhook events that could not be mapped to a unit.
Allows admin resolution or manual mapping later.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class UnmatchedEventStatus(str, enum.Enum):
    """Status of an unmatched webhook event"""
    PENDING = "pending"      # Awaiting resolution
    RESOLVED = "resolved"    # Successfully mapped and processed
    IGNORED = "ignored"      # Admin chose to ignore


class UnmatchedEventReason(str, enum.Enum):
    """Reason why the event could not be matched or was rejected"""
    # Mapping issues
    NO_MAPPING = "no_mapping"            # No mapping for room_type_id or rate_plan_id
    NO_CONNECTION = "no_connection"      # No connection for property_id
    
    # Payload issues
    INVALID_PAYLOAD = "invalid_payload"  # Payload missing required fields
    MISSING_DATES = "missing_dates"      # Check-in or check-out date missing
    MISSING_GUEST = "missing_guest"      # Guest information missing
    
    # Date validation issues
    DATE_CONFLICT = "date_conflict"      # Unit already booked for these dates
    INVALID_DATE_RANGE = "invalid_date_range"  # Check-out before or equal to check-in
    DATES_IN_PAST = "dates_in_past"      # Booking dates are in the past
    DATES_TOO_FAR = "dates_too_far"      # Booking dates too far in the future
    DURATION_TOO_SHORT = "duration_too_short"  # Stay duration too short (< 1 night)
    DURATION_TOO_LONG = "duration_too_long"    # Stay duration too long
    
    # Price issues
    INVALID_PRICE = "invalid_price"      # Price is negative, zero, or unreasonable
    
    # Other
    UNKNOWN = "unknown"                  # Unknown reason


class UnmatchedWebhookEvent(Base):
    """
    Stores webhook events that couldn't be matched to a unit.
    
    Per /chandoc Section 8:
    - Webhooks MUST NOT be dropped silently
    - Must store for admin review
    """
    __tablename__ = "unmatched_webhook_events"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Provider info
    provider = Column(String(50), nullable=False, default="channex")
    event_type = Column(String(50), nullable=True)  # booking_new, booking_modified, etc.
    
    # External identifiers
    external_reservation_id = Column(String(255), nullable=True)
    property_id = Column(String(255), nullable=True)
    room_type_id = Column(String(255), nullable=True)
    rate_plan_id = Column(String(255), nullable=True)
    
    # Raw payload (stored as JSON)
    raw_payload = Column(JSON, nullable=False)
    
    # Resolution info
    reason = Column(String(100), default=UnmatchedEventReason.UNKNOWN.value)
    status = Column(String(50), default=UnmatchedEventStatus.PENDING.value)
    retry_count = Column(Integer, default=0)
    
    # If resolved, link to booking
    resolved_booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    resolved_booking = relationship("Booking", foreign_keys=[resolved_booking_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
    
    __table_args__ = (
        Index("ix_unmatched_provider_reservation", "provider", "external_reservation_id"),
        Index("ix_unmatched_status", "status"),
        Index("ix_unmatched_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<UnmatchedWebhookEvent {self.id} - {self.reason} - {self.status}>"
