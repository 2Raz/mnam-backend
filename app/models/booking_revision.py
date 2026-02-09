"""
Booking Revision Model

Tracks all revisions of a booking from Channex webhooks.
Used for:
- Idempotency (dedupe by revision_id)
- Out-of-order protection
- Audit trail
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Text, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship
from ..database import Base


class BookingRevision(Base):
    """
    Stores every revision of a booking from Channex.
    
    Dedup logic:
    - UNIQUE(external_booking_id, revision_id) prevents duplicate processing
    - 'applied' flag indicates if this revision was applied to the booking
      (False for out-of-order revisions)
    """
    __tablename__ = "booking_revisions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Link to internal booking (nullable for initial creation)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True)
    
    # External identifiers for idempotency
    external_booking_id = Column(String(255), nullable=False)  # Channex reservation ID
    revision_id = Column(String(255), nullable=False)  # Channex revision ID
    
    # Event details
    event_type = Column(String(50), nullable=True)  # new, modification, cancellation
    
    # Full payload from Channex API
    payload = Column(JSON, nullable=True)
    
    # Processing status
    applied = Column(Boolean, default=True)  # False if out-of-order
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    booking = relationship("Booking", backref="revisions")
    
    __table_args__ = (
        # Unique constraint for idempotency
        UniqueConstraint('external_booking_id', 'revision_id', name='uq_booking_revision'),
        # Index for lookups
        Index('ix_booking_revision_booking', 'booking_id'),
        Index('ix_booking_revision_external', 'external_booking_id'),
    )
    
    def __repr__(self):
        return f"<BookingRevision {self.external_booking_id} rev={self.revision_id} applied={self.applied}>"
