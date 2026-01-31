"""
Pricing API Router

Endpoints for managing pricing policies and computing prices.
"""

from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.pricing import PricingPolicy
from ..models.unit import Unit
from ..models.user import User
from ..utils.dependencies import get_current_user
from ..services.pricing_engine import PricingEngine
from ..services.outbox_worker import enqueue_price_update
from ..models.channel_integration import ExternalMapping, ChannelConnection, ConnectionStatus
from ..schemas.pricing import (
    PricingPolicyCreate,
    PricingPolicyUpdate,
    PricingPolicyResponse,
    DailyPriceResponse,
    PriceCalendarResponse,
    RealTimePriceRequest,
    BookingPriceRequest,
    BookingPriceResponse
)

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


# ==================
# Pricing Policy CRUD
# ==================

@router.post("/policies", response_model=PricingPolicyResponse)
async def create_pricing_policy(
    policy_data: PricingPolicyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a pricing policy for a unit"""
    # Check unit exists
    unit = db.query(Unit).filter(Unit.id == policy_data.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="الوحدة غير موجودة")
    
    # Check if policy already exists
    existing = db.query(PricingPolicy).filter(
        PricingPolicy.unit_id == policy_data.unit_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="سياسة التسعير موجودة بالفعل لهذه الوحدة")
    
    policy = PricingPolicy(
        unit_id=policy_data.unit_id,
        base_weekday_price=policy_data.base_weekday_price,
        currency=policy_data.currency,
        weekend_markup_percent=policy_data.weekend_markup_percent,
        discount_16_percent=policy_data.discount_16_percent,
        discount_21_percent=policy_data.discount_21_percent,
        discount_23_percent=policy_data.discount_23_percent,
        timezone=policy_data.timezone,
        weekend_days=policy_data.weekend_days,
        created_by_id=current_user.id
    )
    
    db.add(policy)
    db.commit()
    db.refresh(policy)
    
    # Enqueue price update to channels
    _trigger_price_sync(db, policy_data.unit_id)
    
    return policy


@router.get("/policies/{unit_id}", response_model=PricingPolicyResponse)
async def get_pricing_policy(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get the pricing policy for a unit"""
    policy = db.query(PricingPolicy).filter(
        PricingPolicy.unit_id == unit_id
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    return policy


@router.put("/policies/{unit_id}", response_model=PricingPolicyResponse)
async def update_pricing_policy(
    unit_id: str,
    policy_data: PricingPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update the pricing policy for a unit"""
    policy = db.query(PricingPolicy).filter(
        PricingPolicy.unit_id == unit_id
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    # Update fields
    update_data = policy_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)
    
    policy.updated_by_id = current_user.id
    db.commit()
    db.refresh(policy)
    
    # Enqueue price update to channels
    _trigger_price_sync(db, unit_id)
    
    return policy


@router.delete("/policies/{unit_id}")
async def delete_pricing_policy(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete the pricing policy for a unit"""
    policy = db.query(PricingPolicy).filter(
        PricingPolicy.unit_id == unit_id
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    db.delete(policy)
    db.commit()
    
    return {"message": "تم حذف سياسة التسعير بنجاح"}


@router.post("/sync-prices/{unit_id}")
async def sync_prices_to_channex(
    unit_id: str,
    days_ahead: int = Query(365, description="عدد الأيام للمزامنة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    مزامنة الأسعار مع Channex يدوياً.
    
    يُنشئ حدث في Outbox لمزامنة الأسعار للوحدة المحددة.
    """
    # Check unit exists
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="الوحدة غير موجودة")
    
    # Check if unit has pricing policy
    policy = db.query(PricingPolicy).filter(PricingPolicy.unit_id == unit_id).first()
    if not policy:
        raise HTTPException(status_code=400, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    # Find active mappings
    from sqlalchemy import and_
    mappings = db.query(ExternalMapping).join(ChannelConnection).filter(
        and_(
            ExternalMapping.unit_id == unit_id,
            ExternalMapping.is_active == True,
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        )
    ).all()
    
    if not mappings:
        raise HTTPException(status_code=400, detail="الوحدة غير مربوطة بأي Channel Manager")
    
    # Enqueue price updates
    for mapping in mappings:
        enqueue_price_update(
            db=db,
            unit_id=unit_id,
            connection_id=mapping.connection_id,
            days_ahead=days_ahead
        )
    
    return {
        "message": f"تم إضافة {len(mappings)} طلب مزامنة للأسعار",
        "unit_id": unit_id,
        "days_ahead": days_ahead,
        "mappings_count": len(mappings)
    }


@router.post("/sync-all-prices")
async def sync_all_prices_to_channex(
    days_ahead: int = Query(365, description="عدد الأيام للمزامنة"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    مزامنة أسعار كل الوحدات المربوطة مع Channex.
    
    يُنشئ أحداث في Outbox لمزامنة الأسعار لكل الوحدات المربوطة.
    """
    from sqlalchemy import and_
    
    # Get all active mappings
    mappings = db.query(ExternalMapping).join(ChannelConnection).filter(
        and_(
            ExternalMapping.is_active == True,
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        )
    ).all()
    
    if not mappings:
        raise HTTPException(status_code=400, detail="لا توجد وحدات مربوطة بأي Channel Manager")
    
    # Enqueue price updates for each mapping
    enqueued = 0
    for mapping in mappings:
        try:
            # Check if unit has pricing policy
            policy = db.query(PricingPolicy).filter(PricingPolicy.unit_id == mapping.unit_id).first()
            if policy:
                enqueue_price_update(
                    db=db,
                    unit_id=mapping.unit_id,
                    connection_id=mapping.connection_id,
                    days_ahead=days_ahead
                )
                enqueued += 1
        except Exception:
            pass  # Skip failed enqueues
    
    return {
        "message": f"تم إضافة {enqueued} طلب مزامنة للأسعار",
        "total_mappings": len(mappings),
        "enqueued": enqueued,
        "days_ahead": days_ahead
    }


# ==================
# Price Calculations
# ==================

@router.get("/calendar/{unit_id}", response_model=PriceCalendarResponse)
async def get_price_calendar(
    unit_id: str,
    start_date: Optional[date] = Query(None, description="Start date (defaults to today)"),
    days: int = Query(30, ge=1, le=365, description="Number of days"),
    include_discounts: bool = Query(False, description="Include current intraday discounts"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a price calendar for a unit.
    
    - Set include_discounts=False for base rates (for channels)
    - Set include_discounts=True for real-time prices (for booking display)
    """
    engine = PricingEngine(db)
    
    if start_date is None:
        start_date = date.today()
    
    end_date = start_date + timedelta(days=days - 1)
    
    calendar = engine.generate_price_calendar(
        unit_id=unit_id,
        start_date=start_date,
        end_date=end_date,
        include_discounts=include_discounts
    )
    
    if not calendar:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    return PriceCalendarResponse(
        unit_id=calendar.unit_id,
        start_date=calendar.start_date,
        end_date=calendar.end_date,
        prices=[
            DailyPriceResponse(
                date=p.date,
                base_price=p.base_price,
                day_price=p.day_price,
                final_price=p.final_price,
                is_weekend=p.is_weekend,
                weekend_markup_applied=p.weekend_markup_applied,
                discount_applied=p.discount_applied,
                discount_bucket=p.discount_bucket,
                currency=p.currency
            )
            for p in calendar.prices
        ],
        timezone=calendar.timezone,
        generated_at=calendar.generated_at
    )


@router.get("/realtime/{unit_id}", response_model=DailyPriceResponse)
async def get_realtime_price(
    unit_id: str,
    check_date: Optional[date] = Query(None, description="Date to price (defaults to today)"),
    db: Session = Depends(get_db)
):
    """
    Get the current real-time price for a unit.
    
    This includes any active intraday discount based on current local time.
    Use this for displaying prices to customers making same-day bookings.
    """
    engine = PricingEngine(db)
    
    price = engine.get_realtime_price(unit_id, check_date)
    
    if not price:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    return DailyPriceResponse(
        date=price.date,
        base_price=price.base_price,
        day_price=price.day_price,
        final_price=price.final_price,
        is_weekend=price.is_weekend,
        weekend_markup_applied=price.weekend_markup_applied,
        discount_applied=price.discount_applied,
        discount_bucket=price.discount_bucket,
        currency=price.currency
    )


@router.post("/calculate-booking", response_model=BookingPriceResponse)
async def calculate_booking_price(
    request: BookingPriceRequest,
    db: Session = Depends(get_db)
):
    """
    Calculate total price for a booking.
    
    Returns detailed breakdown by night with totals.
    """
    if request.check_out <= request.check_in:
        raise HTTPException(status_code=400, detail="تاريخ المغادرة يجب أن يكون بعد تاريخ الوصول")
    
    engine = PricingEngine(db)
    
    result = engine.compute_booking_total(
        unit_id=request.unit_id,
        check_in=request.check_in,
        check_out=request.check_out,
        apply_realtime_discount_for_today=request.apply_realtime_discount
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="لا توجد سياسة تسعير لهذه الوحدة")
    
    return BookingPriceResponse(**result)


# ==================
# Helpers
# ==================

def _trigger_price_sync(db: Session, unit_id: str):
    """Trigger price sync to all connected channels"""
    from sqlalchemy import and_
    
    mappings = db.query(ExternalMapping).join(ChannelConnection).filter(
        and_(
            ExternalMapping.unit_id == unit_id,
            ExternalMapping.is_active == True,
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        )
    ).all()
    
    for mapping in mappings:
        try:
            enqueue_price_update(
                db=db,
                unit_id=unit_id,
                connection_id=mapping.connection_id,
                days_ahead=365
            )
        except Exception:
            pass  # Don't fail if enqueue fails
