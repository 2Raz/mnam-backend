"""
Inventory Calendar Model

Daily availability cache per unit.
This is the source of truth for MNAM availability state.
"""

import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Date, DateTime, Boolean, Integer, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from ..database import Base


class InventoryCalendar(Base):
    """
    Daily inventory state for each unit.
    
    Used for:
    - Fast availability lookups
    - Sync to Channex (outbound)
    - Conflict detection
    """
    __tablename__ = "inventory_calendar"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Unit reference
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    
    # Date
    date = Column(Date, nullable=False)
    
    # Availability state
    is_available = Column(Boolean, default=True)
    is_blocked = Column(Boolean, default=False)  # Manual block (maintenance, owner use)
    block_reason = Column(String(100), nullable=True)  # maintenance, owner_block, etc.
    
    # Booking reference (if booked)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    
    # Restrictions (for Channex sync)
    stop_sell = Column(Boolean, default=False)
    min_stay = Column(Integer, nullable=True)
    max_stay = Column(Integer, nullable=True)
    closed_to_arrival = Column(Boolean, default=False)
    closed_to_departure = Column(Boolean, default=False)
    
    # Sync tracking
    last_synced_at = Column(DateTime, nullable=True)
    sync_pending = Column(Boolean, default=False)  # Needs to be synced to Channex
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    unit = relationship("Unit", backref="calendar_entries")
    booking = relationship("Booking", backref="calendar_entries")
    
    __table_args__ = (
        # Unique constraint: one entry per unit per date
        UniqueConstraint('unit_id', 'date', name='uq_inventory_unit_date'),
        # Indexes for common queries
        Index('ix_inventory_unit_date', 'unit_id', 'date'),
        Index('ix_inventory_available', 'unit_id', 'is_available', 'date'),
        Index('ix_inventory_sync_pending', 'sync_pending', 'updated_at'),
    )
    
    def __repr__(self):
        status = "available" if self.is_available else ("blocked" if self.is_blocked else "booked")
        return f"<InventoryCalendar {self.unit_id} {self.date} {status}>"
