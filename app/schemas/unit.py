from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class UnitType(str, Enum):
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


class UnitStatus(str, Enum):
    AVAILABLE = "متاحة"
    BOOKED = "محجوزة"
    CLEANING = "تحتاج تنظيف"
    MAINTENANCE = "صيانة"
    HIDDEN = "مخفية"


class ChannelStatus(str, Enum):
    """حالة ربط الوحدة بالقنوات الخارجية"""
    MAPPED = "mapped"      # مربوط - active mapping exists
    UNMAPPED = "unmapped"  # غير مربوط - no mapping
    DISABLED = "disabled"  # معطل - mapping exists but is_active=False
    ERROR = "error"        # خطأ - mapping has sync errors


class UnitBase(BaseModel):
    project_id: str
    unit_name: str
    unit_type: UnitType = UnitType.APARTMENT
    rooms: int = 1
    floor_number: int = 0
    unit_area: float = 0
    status: UnitStatus = UnitStatus.AVAILABLE
    price_days_of_week: Decimal = Decimal("0")
    price_in_weekends: Decimal = Decimal("0")
    amenities: List[str] = []
    description: Optional[str] = None
    permit_no: Optional[str] = None
    # معلومات الدخول للوحدة
    access_info: Optional[str] = None
    # روابط الحجز: [{"platform": "Airbnb", "url": "https://..."}]
    booking_links: List[Any] = []


class ExternalMappingInfo(BaseModel):
    """معلومات ربط الوحدة بالقنوات الخارجية"""
    id: str
    provider: str = "channex"  # channex, beds24, etc.
    channex_room_type_id: Optional[str] = None
    channex_rate_plan_id: Optional[str] = None
    is_active: bool = True
    last_price_sync_at: Optional[datetime] = None
    last_avail_sync_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UnitCreate(UnitBase):
    """Schema for creating a new unit with optional pricing policy fields"""
    # Legacy pricing fields are inherited from UnitBase
    
    # 🆕 New Dynamic Pricing Fields (optional - for frontend)
    base_weekday_price: Optional[Decimal] = None  # If provided, updates pricing policy
    weekend_markup_percent: Optional[Decimal] = None
    discount_16_percent: Optional[Decimal] = None
    discount_21_percent: Optional[Decimal] = None
    discount_23_percent: Optional[Decimal] = None


class UnitUpdate(BaseModel):
    project_id: Optional[str] = None
    unit_name: Optional[str] = None
    unit_type: Optional[UnitType] = None
    rooms: Optional[int] = None
    floor_number: Optional[int] = None
    unit_area: Optional[float] = None
    status: Optional[UnitStatus] = None
    price_days_of_week: Optional[Decimal] = None
    price_in_weekends: Optional[Decimal] = None
    amenities: Optional[List[str]] = None
    description: Optional[str] = None
    permit_no: Optional[str] = None
    # معلومات الدخول للوحدة
    access_info: Optional[str] = None
    # روابط الحجز
    booking_links: Optional[List[Any]] = None
    
    # 🆕 New Dynamic Pricing Fields (optional)
    base_weekday_price: Optional[Decimal] = None
    weekend_markup_percent: Optional[Decimal] = None
    discount_16_percent: Optional[Decimal] = None
    discount_21_percent: Optional[Decimal] = None
    discount_23_percent: Optional[Decimal] = None


class UnitResponse(UnitBase):
    id: str
    project_name: str = ""
    owner_name: str = ""
    city: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # 🆕 Pricing policy info (if available)
    pricing_policy: Optional[dict] = None
    
    # 🆕 Channel Integration - External Mappings
    external_mappings: List[ExternalMappingInfo] = []
    has_channex_connection: bool = False  # عرض سريع لحالة الربط
    channel_status: str = "unmapped"  # mapped, unmapped, disabled, error
    
    class Config:
        from_attributes = True


class UnitSimple(BaseModel):
    unit_name: str
    unit_type: str
    rooms: int
    price_days_of_week: Decimal
    price_in_weekends: Decimal
    status: str


class UnitForSelect(BaseModel):
    id: str
    unit_name: str
    price_days_of_week: Decimal
    price_in_weekends: Decimal
    
    class Config:
        from_attributes = True
