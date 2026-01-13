from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from decimal import Decimal
from enum import Enum


class BookingStatus(str, Enum):
    CONFIRMED = "مؤكد"
    CANCELLED = "ملغي"
    COMPLETED = "مكتمل"
    CHECKED_IN = "دخول"
    CHECKED_OUT = "خروج"


class BookingBase(BaseModel):
    unit_id: str
    guest_name: str
    guest_phone: Optional[str] = None
    check_in_date: date
    check_out_date: date
    total_price: Decimal = Decimal("0")
    status: BookingStatus = BookingStatus.CONFIRMED
    notes: Optional[str] = None


class GuestGender(str, Enum):
    """جنس الضيف (اختياري)"""
    MALE = "male"
    FEMALE = "female"


class BookingCreate(BaseModel):
    project_id: str
    unit_id: str
    guest_name: str
    guest_phone: Optional[str] = None
    guest_gender: Optional[GuestGender] = None  # جنس الضيف (اختياري) - Auto Customer Sync
    check_in_date: date
    check_out_date: date
    total_price: Decimal
    status: BookingStatus = BookingStatus.CONFIRMED
    notes: Optional[str] = None


class BookingUpdate(BaseModel):
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    guest_gender: Optional[GuestGender] = None  # جنس الضيف (اختياري)
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    total_price: Optional[Decimal] = None
    status: Optional[BookingStatus] = None
    notes: Optional[str] = None


class BookingStatusUpdate(BaseModel):
    status: BookingStatus


class BookingResponse(BookingBase):
    id: str
    project_id: str = ""
    project_name: str = ""
    unit_name: str = ""
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_is_banned: bool = False
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class BookingAvailabilityCheck(BaseModel):
    unit_id: str
    check_in_date: date
    check_out_date: date
    exclude_booking_id: Optional[str] = None
