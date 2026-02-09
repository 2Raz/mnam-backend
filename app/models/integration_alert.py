"""
Integration Alert Model

Stores alerts from health webhooks and integration errors.
These are visible in the MNAM dashboard for operations team.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSON
from ..database import Base
import enum


class AlertType(str, enum.Enum):
    """Types of integration alerts"""
    UNMAPPED_ROOM = "unmapped_room"
    UNMAPPED_RATE = "unmapped_rate"
    SYNC_ERROR = "sync_error"
    RATE_ERROR = "rate_error"
    NON_ACKED = "non_acked"
    WEBHOOK_FAILED = "webhook_failed"
    CHANNEL_ERROR = "channel_error"


class AlertSeverity(str, enum.Enum):
    """Alert severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    """Alert lifecycle status"""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class IntegrationAlert(Base):
    """
    Stores integration alerts for operations visibility.
    
    Created by:
    - Health webhook events
    - Failed webhook processing
    - Sync errors
    """
    __tablename__ = "integration_alerts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Source identification
    provider = Column(String(50), default="channex", nullable=False)
    property_id = Column(String(255), nullable=True)
    connection_id = Column(String(36), nullable=True)  # MNAM connection ID
    
    # Alert details
    alert_type = Column(String(50), nullable=False)  # AlertType enum value
    severity = Column(String(20), default=AlertSeverity.MEDIUM.value)
    message = Column(Text, nullable=True)
    
    # Raw data for debugging
    payload_raw = Column(JSON, nullable=True)
    
    # Lifecycle
    status = Column(String(20), default=AlertStatus.OPEN.value)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by_id = Column(String(36), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(String(36), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_alert_status', 'status', 'created_at'),
        Index('ix_alert_type', 'alert_type', 'severity'),
        Index('ix_alert_property', 'property_id', 'status'),
    )
    
    def __repr__(self):
        return f"<IntegrationAlert {self.alert_type} {self.severity} {self.status}>"
