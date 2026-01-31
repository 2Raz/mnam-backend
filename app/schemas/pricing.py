"""
Pricing Schemas

Pydantic models for pricing API requests and responses.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class PricingPolicyBase(BaseModel):
    """Base schema for pricing policy"""
    base_weekday_price: Decimal = Field(..., ge=0, description="Base price for weekdays")
    currency: str = Field(default="SAR", max_length=3)
    weekend_markup_percent: Decimal = Field(default=0, ge=0, le=500, description="Weekend markup as percentage")
    discount_16_percent: Decimal = Field(default=0, ge=0, le=100, description="Discount from 16:00-20:59")
    discount_21_percent: Decimal = Field(default=0, ge=0, le=100, description="Discount from 21:00-22:59")
    discount_23_percent: Decimal = Field(default=0, ge=0, le=100, description="Discount from 23:00-23:59")
    timezone: str = Field(default="Asia/Riyadh", description="Timezone for discount calculation")
    weekend_days: str = Field(default="4,5", description="Comma-separated weekend day numbers (0=Mon, 6=Sun)")
    
    @field_validator('weekend_days')
    @classmethod
    def validate_weekend_days(cls, v):
        if v:
            for d in v.split(","):
                if d.strip() and not d.strip().isdigit():
                    raise ValueError("weekend_days must be comma-separated numbers")
                if d.strip() and int(d.strip()) not in range(7):
                    raise ValueError("weekend_days values must be 0-6")
        return v


class PricingPolicyCreate(PricingPolicyBase):
    """Schema for creating a pricing policy"""
    unit_id: str = Field(..., description="Unit ID to attach policy to")


class PricingPolicyUpdate(BaseModel):
    """Schema for updating a pricing policy"""
    base_weekday_price: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=3)
    weekend_markup_percent: Optional[Decimal] = Field(None, ge=0, le=500)
    discount_16_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_21_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    discount_23_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    timezone: Optional[str] = None
    weekend_days: Optional[str] = None


class PricingPolicyResponse(PricingPolicyBase):
    """Schema for pricing policy response"""
    id: str
    unit_id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class DailyPriceResponse(BaseModel):
    """Schema for a single day's price"""
    date: date
    base_price: Decimal
    day_price: Decimal  # After weekend markup
    final_price: Decimal  # After discount
    is_weekend: bool
    weekend_markup_applied: Decimal
    discount_applied: Decimal
    discount_bucket: str
    currency: str


class PriceCalendarResponse(BaseModel):
    """Schema for a price calendar"""
    unit_id: str
    start_date: date
    end_date: date
    prices: List[DailyPriceResponse]
    timezone: str
    generated_at: datetime


class RealTimePriceRequest(BaseModel):
    """Request for real-time price"""
    unit_id: str
    check_date: Optional[date] = None  # Defaults to today


class BookingPriceRequest(BaseModel):
    """Request for booking total calculation"""
    unit_id: str
    check_in: date
    check_out: date
    apply_realtime_discount: bool = True


class BookingPriceNight(BaseModel):
    """Single night breakdown in booking price"""
    date: str
    price: str
    is_weekend: bool
    discount_applied: Optional[str] = None


class BookingPriceResponse(BaseModel):
    """Response for booking total calculation"""
    unit_id: str
    check_in: str
    check_out: str
    num_nights: int
    nights: List[BookingPriceNight]
    total: str
    currency: str
