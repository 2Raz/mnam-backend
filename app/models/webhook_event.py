"""
Webhook Event Log Model

Stores raw webhook events for async processing.
This is a separate table from InboundIdempotency to support:
- Fast acknowledgment (return 200 immediately)
- Async processing by worker
- Full audit trail of raw payloads
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Index, JSON
from ..database import Base
import enum


class WebhookEventStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Duplicate event


class WebhookEventLog(Base):
    """
    Raw webhook event storage for async processing.
    
    Webhook router:
    1. Validates request basics
    2. Persists raw event to this table
    3. Returns 200 immediately
    
    Worker:
    1. Picks up RECEIVED events
    2. Processes them via ChannexWebhookHandler
    3. Updates status to PROCESSED/FAILED
    """
    __tablename__ = "webhook_event_logs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Provider identification
    provider = Column(String(50), default="channex", nullable=False)
    
    # External identifiers for idempotency
    event_id = Column(String(255), nullable=True)  # From webhook payload
    event_type = Column(String(100), nullable=True)  # booking.new, booking.modified, etc.
    
    # For idempotency lookup
    external_id = Column(String(255), nullable=True)  # booking/reservation ID
    revision_id = Column(String(255), nullable=True)  # For modifications
    
    # Raw payload
    payload_json = Column(Text, nullable=False)  # Store as JSON string
    request_headers = Column(Text, nullable=True)  # For debugging/verification
    
    # Processing status
    status = Column(String(20), default=WebhookEventStatus.RECEIVED.value)
    
    # Processing result
    processed_at = Column(DateTime, nullable=True)
    result_action = Column(String(50), nullable=True)  # created, updated, cancelled, skipped
    result_booking_id = Column(String(36), nullable=True)  # Internal booking ID if created/updated
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    received_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        # Unique constraint for idempotency based on best available keys
        Index("ix_webhook_event_provider_event_id", "provider", "event_id"),
        Index("ix_webhook_event_status", "status", "received_at"),
        Index("ix_webhook_event_external", "provider", "external_id", "revision_id"),
    )
    
    def __repr__(self):
        return f"<WebhookEventLog {self.provider} {self.event_type} status={self.status}>"
