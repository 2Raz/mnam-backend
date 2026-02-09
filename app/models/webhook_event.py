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
from sqlalchemy import Column, String, Text, DateTime, Index, Integer
from sqlalchemy.dialects.postgresql import JSON
from ..database import Base
import enum


class WebhookEventStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Duplicate event
    IGNORED = "ignored"  # Intentionally not processed


class ErrorCode(str, enum.Enum):
    """Error classification for retry logic"""
    TRANSIENT = "transient"  # Retry-able (timeout, 429, 5xx)
    PERMANENT = "permanent"  # Don't retry (400, validation)


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
    
    # Endpoint type (NEW: for dual webhook routing)
    endpoint_type = Column(String(50), nullable=True)  # bookings, health
    
    # Property ID (NEW: for filtering and rate limiting)
    property_id = Column(String(255), nullable=True)  # Channex property ID
    
    # External identifiers for idempotency
    event_id = Column(String(255), nullable=True)  # From webhook payload
    event_type = Column(String(100), nullable=True)  # new, modification, cancellation
    
    # For idempotency lookup
    external_id = Column(String(255), nullable=True)  # booking/reservation ID
    revision_id = Column(String(255), nullable=True)  # For modifications
    
    # Raw payload
    payload_json = Column(Text, nullable=False)  # Store as JSON string
    payload_hash = Column(String(64), nullable=True)  # SHA256 for dedup (NEW)
    request_headers = Column(Text, nullable=True)  # For debugging/verification
    
    # Processing status
    status = Column(String(20), default=WebhookEventStatus.RECEIVED.value)
    
    # Retry logic (NEW)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    next_retry_at = Column(DateTime, nullable=True)
    error_code = Column(String(20), nullable=True)  # transient, permanent
    
    # Worker locking (NEW: for multiple workers)
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(100), nullable=True)  # Worker identifier
    
    # Processing timestamps (NEW)
    processing_started_at = Column(DateTime, nullable=True)
    processing_finished_at = Column(DateTime, nullable=True)
    
    # Processing result
    processed_at = Column(DateTime, nullable=True)
    result_action = Column(String(50), nullable=True)  # created, updated, cancelled, skipped
    result_booking_id = Column(String(36), nullable=True)  # Internal booking ID if created/updated
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    received_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        # Unique constraint for idempotency based on payload hash
        Index("ix_webhook_event_provider_hash", "provider", "payload_hash"),
        # Original indexes
        Index("ix_webhook_event_provider_event_id", "provider", "event_id"),
        Index("ix_webhook_event_status", "status", "received_at"),
        Index("ix_webhook_event_external", "provider", "external_id", "revision_id"),
        # New indexes
        Index("ix_webhook_event_property", "property_id", "event_type", "received_at"),
        Index("ix_webhook_event_retry", "status", "next_retry_at"),
    )
    
    def __repr__(self):
        return f"<WebhookEventLog {self.provider} {self.event_type} status={self.status}>"
