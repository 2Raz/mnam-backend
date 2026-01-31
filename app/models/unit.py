import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Numeric, Text, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.orm import relationship
from ..database import Base
import enum


class UnitType(str, enum.Enum):
    APARTMENT = "شقة"
    STUDIO = "استوديو"
    VILLA = "فيلا"
    CHALET = "شاليه"
    FARMHOUSE = "بيت ريفي"
    REST_HOUSE = "استراحة"
    CARAVAN = "كرفان"
    CAMP = "مخيم"
    DUPLEX = "دوبلكس"
    TOWNHOUSE = "تاون هاوس"


class UnitStatus(str, enum.Enum):
    AVAILABLE = "متاحة"
    BOOKED = "محجوزة"
    CLEANING = "تحتاج تنظيف"
    MAINTENANCE = "صيانة"
    HIDDEN = "مخفية"


class Unit(Base):
    __tablename__ = "units"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    unit_name = Column(String(100), nullable=False)
    unit_type = Column(String(30), default=UnitType.APARTMENT.value)
    rooms = Column(Integer, default=1)
    floor_number = Column(Integer, default=0)
    unit_area = Column(Float, default=0)
    status = Column(String(30), default=UnitStatus.AVAILABLE.value)
    price_days_of_week = Column(Numeric(10, 2), default=0)
    price_in_weekends = Column(Numeric(10, 2), default=0)
    amenities = Column(JSON, default=list)
    description = Column(Text, nullable=True)
    permit_no = Column(String(50), nullable=True)
    
    # معلومات الدخول للوحدة
    access_info = Column(Text, nullable=True)
    
    # روابط الحجز: [{"platform": "Airbnb", "url": "https://..."}, ...]
    booking_links = Column(JSON, default=list)
    
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
    project = relationship("Project", back_populates="units")
    bookings = relationship("Booking", back_populates="unit", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="unit")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    
    # Pricing & Channel Integration
    pricing_policy = relationship("PricingPolicy", back_populates="unit", uselist=False, cascade="all, delete-orphan")
    external_mappings = relationship("ExternalMapping", back_populates="unit", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Unit {self.unit_name}>"

