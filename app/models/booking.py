import uuid
from datetime import datetime
from sqlalchemy import Column, String, Date, Numeric, Text, ForeignKey, DateTime, Index, Boolean
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class BookingStatus(str, enum.Enum):
    CONFIRMED = "مؤكد"
    CANCELLED = "ملغي"
    COMPLETED = "مكتمل"
    CHECKED_IN = "دخول"
    CHECKED_OUT = "خروج"


class SourceType(str, enum.Enum):
    """How the booking arrived in MNAM"""
    MANUAL = "manual"        # Created manually in MNAM dashboard
    CHANNEX = "channex"      # Received via Channex webhook
    DIRECT_API = "direct_api"  # Imported via direct API


class BookingSource(str, enum.Enum):
    """The actual OTA channel the booking came from"""
    DIRECT = "direct"  # Created in MNAM
    AIRBNB = "airbnb"
    BOOKING_COM = "booking.com"
    EXPEDIA = "expedia"
    AGODA = "agoda"
    GATHERN = "gathern"
    CHANNEX = "channex"  # Via Channex but unknown OTA
    OTHER_OTA = "other_ota"
    UNKNOWN = "unknown"


class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    guest_name = Column(String(100), nullable=False)
    guest_phone = Column(String(20), nullable=True)
    guest_email = Column(String(255), nullable=True)  # For OTA guests
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)
    total_price = Column(Numeric(10, 2), default=0)
    status = Column(String(30), default=BookingStatus.CONFIRMED.value)
    notes = Column(Text, nullable=True)
    
    # Channel Integration - External Booking Tracking
    source_type = Column(String(50), default=SourceType.MANUAL.value)  # How it arrived
    channel_source = Column(String(50), default=BookingSource.DIRECT.value)  # Actual OTA platform
    external_reservation_id = Column(String(255), nullable=True)  # OTA booking ID
    external_revision_id = Column(String(255), nullable=True)  # For modification tracking
    channel_data = Column(Text, nullable=True)  # JSON string with original OTA data
    
    # تتبع الموظفين
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Soft Delete
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    unit = relationship("Unit", back_populates="bookings")
    customer = relationship("Customer", back_populates="bookings")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    
    __table_args__ = (
        Index("ix_booking_external_reservation", "external_reservation_id"),
        Index("ix_booking_channel_source", "channel_source"),
        Index("ix_booking_source_type", "source_type"),
    )
    
    def __repr__(self):
        return f"<Booking {self.guest_name} - {self.check_in_date}>"


