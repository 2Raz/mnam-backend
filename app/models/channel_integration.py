"""
Channel Integration Models

Models for managing channel manager connections (Channex) including:
- ChannelConnection: Store API credentials and connection status
- ExternalMapping: Map internal units/rate plans to channel IDs
- IntegrationOutbox: Queue for outbound events (prices, availability)
- IntegrationLog: Observability logs for all integration activities
- InboundIdempotency: Track processed webhook events
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Numeric, ForeignKey, DateTime, Integer, Boolean, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class ConnectionStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    PENDING = "pending"


class OutboxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class OutboxEventType(str, enum.Enum):
    PRICE_UPDATE = "price_update"
    AVAIL_UPDATE = "avail_update"
    FULL_SYNC = "full_sync"


class ChannelConnection(Base):
    """
    Stores connection credentials and status for channel managers like Channex.
    One connection per company (project owner context).
    """
    __tablename__ = "channel_connections"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Context - which company/owner this connection belongs to
    # Using project_id as the company context for now
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    # Provider info
    provider = Column(String(50), default="channex", nullable=False)  # "channex", "beds24", etc.
    
    # Credentials (encrypted in production)
    api_key = Column(Text, nullable=False)
    
    # Channex-specific identifiers
    channex_property_id = Column(String(100), nullable=True)
    channex_group_id = Column(String(100), nullable=True)
    
    # Webhook configuration
    webhook_secret = Column(String(255), nullable=True)
    webhook_url = Column(String(500), nullable=True)
    
    # Status tracking
    status = Column(String(20), default=ConnectionStatus.PENDING.value)
    last_sync_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    error_count = Column(Integer, default=0)
    
    # Rate limiting
    requests_today = Column(Integer, default=0)
    rate_limit_reset_at = Column(DateTime, nullable=True)
    
    # Tracking
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete
    
    # Relationships
    project = relationship("Project", back_populates="channel_connections")
    external_mappings = relationship("ExternalMapping", back_populates="connection", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_id])
    
    def __repr__(self):
        return f"<ChannelConnection {self.provider} project={self.project_id}>"


class ExternalMapping(Base):
    """
    Maps internal MNAM entities to external channel manager IDs.
    Supports mapping units to room types and rate plans.
    """
    __tablename__ = "external_mappings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id = Column(String(36), ForeignKey("channel_connections.id", ondelete="CASCADE"), nullable=False)
    
    # Internal references
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="CASCADE"), nullable=True)
    
    # External Channex identifiers
    channex_room_type_id = Column(String(100), nullable=True)
    channex_rate_plan_id = Column(String(100), nullable=True)
    
    # Mapping type for clarity
    mapping_type = Column(String(50), default="unit_to_room")  # "unit_to_room", "rate_plan"
    
    # Sync status
    is_active = Column(Boolean, default=True)
    last_price_sync_at = Column(DateTime, nullable=True)
    last_avail_sync_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    connection = relationship("ChannelConnection", back_populates="external_mappings")
    unit = relationship("Unit", back_populates="external_mappings")
    
    __table_args__ = (
        Index("ix_external_mapping_unit", "unit_id"),
        Index("ix_external_mapping_connection", "connection_id"),
        UniqueConstraint('connection_id', 'unit_id', name='uq_external_mapping_connection_unit'),
    )
    
    def __repr__(self):
        return f"<ExternalMapping unit={self.unit_id} room_type={self.channex_room_type_id}>"


class IntegrationOutbox(Base):
    """
    Outbox pattern for reliable outbound events.
    Events are queued here and processed by a background worker.
    """
    __tablename__ = "integration_outbox"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Event context
    connection_id = Column(String(36), ForeignKey("channel_connections.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)  # PRICE_UPDATE, AVAIL_UPDATE
    
    # Payload
    payload = Column(JSON, nullable=False)  # Contains data to send to channel
    
    # Targeting (optional - for filtering)
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    date_from = Column(DateTime, nullable=True)  # For date-ranged updates
    date_to = Column(DateTime, nullable=True)
    
    # Processing status
    status = Column(String(20), default=OutboxStatus.PENDING.value)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=5)
    next_attempt_at = Column(DateTime, default=datetime.utcnow)
    
    # Result tracking
    last_error = Column(Text, nullable=True)
    response_data = Column(JSON, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Idempotency key for deduplication
    idempotency_key = Column(String(255), nullable=True, unique=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    connection = relationship("ChannelConnection")
    unit = relationship("Unit")
    
    __table_args__ = (
        Index("ix_outbox_status_next", "status", "next_attempt_at"),
        Index("ix_outbox_connection", "connection_id"),
    )
    
    def __repr__(self):
        return f"<IntegrationOutbox {self.event_type} status={self.status}>"


class IntegrationLog(Base):
    """
    Observability logs for all integration activities.
    Tracks API calls, webhooks received, and processing results.
    """
    __tablename__ = "integration_logs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Context
    connection_id = Column(String(36), ForeignKey("channel_connections.id", ondelete="SET NULL"), nullable=True)
    outbox_id = Column(String(36), ForeignKey("integration_outbox.id", ondelete="SET NULL"), nullable=True)
    
    # Log details
    log_type = Column(String(50), nullable=False)  # "api_call", "webhook_received", "error", "info"
    direction = Column(String(20), nullable=False)  # "inbound", "outbound"
    event_type = Column(String(50), nullable=True)  # "booking_created", "price_push", etc.
    
    # Request/Response (sanitized - no secrets)
    request_method = Column(String(10), nullable=True)
    request_url = Column(String(500), nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)
    
    # Status
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_integration_log_connection", "connection_id"),
        Index("ix_integration_log_created", "created_at"),
        Index("ix_integration_log_type", "log_type", "direction"),
    )
    
    def __repr__(self):
        return f"<IntegrationLog {self.log_type} {self.direction}>"


class InboundIdempotency(Base):
    """
    Track processed webhook events for idempotency.
    Prevents duplicate processing of the same booking event.
    """
    __tablename__ = "inbound_idempotency"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # External identifiers
    provider = Column(String(50), nullable=False)  # "channex"
    external_event_id = Column(String(255), nullable=False)  # Webhook event ID
    external_reservation_id = Column(String(255), nullable=True)
    revision_id = Column(String(255), nullable=True)  # For booking modifications
    
    # Processing result
    processed_at = Column(DateTime, default=datetime.utcnow)
    result_action = Column(String(50), nullable=True)  # "created", "updated", "cancelled", "skipped"
    internal_booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Unique constraint for idempotency
    __table_args__ = (
        Index("ix_inbound_idempotency_external", "provider", "external_event_id", unique=True),
        Index("ix_inbound_idempotency_reservation", "provider", "external_reservation_id"),
    )
    
    def __repr__(self):
        return f"<InboundIdempotency {self.provider} event={self.external_event_id}>"


class AuditDirection(str, enum.Enum):
    OUTBOUND = "outbound"  # MNAM -> Channex
    INBOUND = "inbound"    # Channex -> MNAM


class AuditEntityType(str, enum.Enum):
    AVAILABILITY = "availability"
    RATE = "rate"
    RESTRICTIONS = "restrictions"
    BOOKING = "booking"
    FULL_SYNC = "full_sync"


class IntegrationAudit(Base):
    """
    Audit trail for all integration sync operations.
    
    Tracks every sync attempt (success/fail) with:
    - Direction (inbound/outbound)
    - Entity type (availability/rate/restrictions/booking)
    - Payload hash for verification
    - Retry count and error details
    """
    __tablename__ = "integration_audit"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Context
    connection_id = Column(String(36), ForeignKey("channel_connections.id", ondelete="SET NULL"), nullable=True)
    
    # What was synced
    direction = Column(String(20), nullable=False)  # outbound / inbound
    entity_type = Column(String(50), nullable=False)  # availability / rate / restrictions / booking
    
    # External references
    external_id = Column(String(255), nullable=True)  # Channex booking ID, etc.
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    
    # Payload tracking (hash for integrity, not full payload to save space)
    payload_hash = Column(String(64), nullable=True)  # SHA256 of payload
    payload_size_bytes = Column(Integer, nullable=True)
    
    # Date range for ARI updates
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    records_count = Column(Integer, nullable=True)  # number of dates/items in sync
    
    # Result
    status = Column(String(20), nullable=False)  # pending, success, failed, retrying
    error_message = Column(Text, nullable=True)
    
    # Retry tracking
    retry_count = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Correlation
    request_id = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    connection = relationship("ChannelConnection")
    unit = relationship("Unit")
    
    __table_args__ = (
        Index("ix_integration_audit_direction", "direction"),
        Index("ix_integration_audit_entity", "entity_type"),
        Index("ix_integration_audit_status", "status"),
        Index("ix_integration_audit_connection", "connection_id"),
        Index("ix_integration_audit_created", "created_at"),
    )
    
    def __repr__(self):
        return f"<IntegrationAudit {self.direction} {self.entity_type} status={self.status}>"
