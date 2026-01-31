from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, TYPE_CHECKING, Any, Literal
from datetime import datetime
from enum import Enum
import re


class GenderEnum(str, Enum):
    """أنواع الجنس"""
    MALE = "male"  # ذكر
    FEMALE = "female"  # أنثى


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="اسم العميل")
    phone: str = Field(..., min_length=5, max_length=20, description="رقم الهاتف")
    email: Optional[EmailStr] = None
    gender: Optional[GenderEnum] = None
    notes: Optional[str] = Field(None, max_length=2000, description="ملاحظات")
    
    @field_validator('name', 'notes', mode='before')
    @classmethod
    def sanitize_text_fields(cls, v):
        """XSS تعقيم الحقول النصية لمنع"""
        if v is None:
            return v
        if isinstance(v, str):
            # إزالة script tags و event handlers
            v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
            v = re.sub(r'on\w+\s*=', '', v, flags=re.IGNORECASE)
        return v


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    gender: Optional[GenderEnum] = None
    notes: Optional[str] = Field(None, max_length=2000)
    is_banned: Optional[bool] = None
    ban_reason: Optional[str] = Field(None, max_length=500)
    
    @field_validator('name', 'notes', 'ban_reason', mode='before')
    @classmethod
    def sanitize_text_fields(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
            v = re.sub(r'on\w+\s*=', '', v, flags=re.IGNORECASE)
        return v


class CustomerBanUpdate(BaseModel):
    is_banned: bool
    ban_reason: Optional[str] = None


class CustomerResponse(CustomerBase):
    id: str
    booking_count: int = 0
    completed_booking_count: int = 0  # عدد الحجوزات المكتملة
    total_revenue: float = 0.0  # إجمالي الإيراد
    is_banned: bool = False
    ban_reason: Optional[str] = None
    is_profile_complete: bool = False  # هل البيانات مكتملة
    visitor_type: str = "عادي"  # نوع الزائر: مميز / عادي
    customer_status: str = "new"  # حالة العميل: new / old
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class CustomerWithBookings(CustomerResponse):
    """العميل مع قائمة حجوزاته"""
    bookings: List[Any] = []


class CustomerStatsResponse(BaseModel):
    """إحصائيات العملاء"""
    total_customers: int = 0
    new_customers: int = 0  # العملاء الجدد (أقل من أسبوعين)
    old_customers: int = 0  # العملاء القدامى (أكثر من أسبوعين)
    vip_customers: int = 0  # العملاء المميزين (زيارتين أو أكثر)
    regular_customers: int = 0  # العملاء العاديين (زيارة واحدة)
    complete_profiles: int = 0  # البيانات المكتملة
    incomplete_profiles: int = 0  # البيانات الغير مكتملة
    total_revenue: float = 0.0  # إجمالي الإيرادات من جميع العملاء

