from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, Any
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
import html


class BookingStatus(str, Enum):
    CONFIRMED = "مؤكد"
    CANCELLED = "ملغي"
    COMPLETED = "مكتمل"
    CHECKED_IN = "دخول"
    CHECKED_OUT = "خروج"


class SourceType(str, Enum):
    """مصدر الحجز - كيف وصل الحجز للنظام"""
    MANUAL = "manual"        # تم إنشاؤه يدوياً في MNAM
    CHANNEX = "channex"      # وصل عبر Channex webhook
    DIRECT_API = "direct_api"  # تم استيراده عبر API مباشر


class ChannelSource(str, Enum):
    """القناة الفعلية التي جاء منها الحجز"""
    DIRECT = "direct"           # حجز مباشر في MNAM
    AIRBNB = "airbnb"
    BOOKING_COM = "booking.com"
    EXPEDIA = "expedia"
    AGODA = "agoda"
    GATHERN = "gathern"
    OTHER_OTA = "other_ota"
    UNKNOWN = "unknown"


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
    project_id: str = Field(..., min_length=1, max_length=100)
    unit_id: str = Field(..., min_length=1, max_length=100)
    guest_name: str = Field(..., min_length=1, max_length=200, description="اسم الضيف")
    guest_phone: Optional[str] = Field(None, max_length=20, description="رقم الهاتف")
    guest_gender: Optional[GuestGender] = None
    check_in_date: date
    check_out_date: date
    total_price: Optional[Decimal] = Field(None, ge=0, description="السعر الإجمالي")
    status: BookingStatus = BookingStatus.CONFIRMED
    notes: Optional[str] = Field(None, max_length=2000, description="ملاحظات")
    channel_source: Optional[str] = Field(None, max_length=100)
    
    @field_validator('guest_name', 'notes', mode='before')
    @classmethod
    def sanitize_text_fields(cls, v):
        """XSS تعقيم الحقول النصية لمنع"""
        if v is None:
            return v
        if isinstance(v, str):
            # إزالة script tags و event handlers
            import re
            v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
            v = re.sub(r'on\w+\s*=', '', v, flags=re.IGNORECASE)
        return v
    
    @model_validator(mode='after')
    def validate_dates(self):
        """validate that check_out_date is after check_in_date"""
        if self.check_out_date <= self.check_in_date:
            raise ValueError('تاريخ الخروج يجب أن يكون بعد تاريخ الدخول')
        return self


class BookingUpdate(BaseModel):
    guest_name: Optional[str] = Field(None, max_length=200)
    guest_phone: Optional[str] = Field(None, max_length=20)
    guest_gender: Optional[GuestGender] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    total_price: Optional[Decimal] = Field(None, ge=0)
    status: Optional[BookingStatus] = None
    notes: Optional[str] = Field(None, max_length=2000)
    
    @field_validator('guest_name', 'notes', mode='before')
    @classmethod
    def sanitize_text_fields(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            import re
            v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
            v = re.sub(r'on\w+\s*=', '', v, flags=re.IGNORECASE)
        return v


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
    
    # Channel Integration - Booking Source Tracking
    source_type: str = "manual"  # manual | channex | direct_api
    channel_source: str = "direct"  # direct | airbnb | booking.com | gathern | etc.
    external_reservation_id: Optional[str] = None  # معرف الحجز الخارجي
    external_revision_id: Optional[str] = None  # معرف التعديل
    channel_data: Optional[Dict[str, Any]] = None  # بيانات القناة الخام
    guest_email: Optional[str] = None  # البريد الإلكتروني للضيف (من OTA)
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class BookingAvailabilityCheck(BaseModel):
    unit_id: str
    check_in_date: date
    check_out_date: date
    exclude_booking_id: Optional[str] = None
