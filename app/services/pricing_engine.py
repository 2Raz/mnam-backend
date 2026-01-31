"""
Pricing Engine Service

Computes daily prices for units based on:
- Base weekday price
- Weekend markup percentage
- Time-based intraday discounts (16:00, 21:00, 23:00 local time)

The engine provides two modes:
1. Calendar generation: Compute prices for a full date range
2. Incremental update: Compute only affected dates when policy changes
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models.pricing import PricingPolicy
from ..models.unit import Unit


@dataclass
class DailyPrice:
    """Represents computed price for a single day"""
    date: date
    base_price: Decimal
    day_price: Decimal  # After weekend markup
    final_price: Decimal  # After discount
    is_weekend: bool
    weekend_markup_applied: Decimal
    discount_applied: Decimal
    discount_bucket: str  # "none", "16", "21", "23"
    currency: str


@dataclass
class PriceCalendar:
    """Collection of daily prices for a unit"""
    unit_id: str
    start_date: date
    end_date: date
    prices: List[DailyPrice]
    policy_snapshot: dict  # Copy of policy used for calculation
    generated_at: datetime
    timezone: str


class PricingEngine:
    """
    Core pricing engine for computing unit prices.
    
    Pricing Formula:
    1. base = base_weekday_price
    2. day_price = base if weekday else base * (1 + weekend_markup_percent/100)
    3. active_discount = discount bucket based on local time (0, 16, 21, 23)
    4. final_price = round(day_price * (1 - active_discount/100), 2)
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_policy_for_unit(self, unit_id: str) -> Optional[PricingPolicy]:
        """Get the pricing policy for a unit"""
        return self.db.query(PricingPolicy).filter(
            PricingPolicy.unit_id == unit_id
        ).first()
    
    def get_current_discount_bucket(
        self,
        policy: PricingPolicy,
        current_time: Optional[datetime] = None
    ) -> Tuple[str, Decimal]:
        """
        Determine which discount bucket is active based on local time.
        
        Returns:
            Tuple of (bucket_name, discount_percent)
            bucket_name: "none", "16", "21", "23"
        """
        if current_time is None:
            # Get current time in policy timezone
            tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
            current_time = datetime.now(tz)
        elif current_time.tzinfo is None:
            # If naive datetime, assume it's in policy timezone
            tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
            current_time = current_time.replace(tzinfo=tz)
        
        hour = current_time.hour
        
        if hour >= 23:
            return ("23", Decimal(str(policy.discount_23_percent or 0)))
        elif hour >= 21:
            return ("21", Decimal(str(policy.discount_21_percent or 0)))
        elif hour >= 16:
            return ("16", Decimal(str(policy.discount_16_percent or 0)))
        else:
            return ("none", Decimal("0"))
    
    def is_weekend_day(self, check_date: date, policy: PricingPolicy) -> bool:
        """
        Check if a date is a weekend day according to policy.
        
        Default KSA weekend: Friday (4) and Saturday (5)
        Python weekday(): Monday=0, Tuesday=1, ..., Sunday=6
        """
        weekend_days = policy.get_weekend_days()
        return check_date.weekday() in weekend_days
    
    def compute_day_price(
        self,
        policy: PricingPolicy,
        check_date: date,
        current_time: Optional[datetime] = None
    ) -> DailyPrice:
        """
        Compute the price for a single day.
        
        Args:
            policy: PricingPolicy for the unit
            check_date: The date to compute price for
            current_time: Optional current time for discount calculation
                         If None, uses current time. If provided, uses that time.
        
        Returns:
            DailyPrice with all computed values
        """
        base_price = Decimal(str(policy.base_weekday_price))
        is_weekend = self.is_weekend_day(check_date, policy)
        
        # Step 1: Apply weekend markup if applicable
        if is_weekend:
            weekend_markup = Decimal(str(policy.weekend_markup_percent or 0))
            day_price = base_price * (1 + weekend_markup / 100)
            weekend_markup_applied = weekend_markup
        else:
            day_price = base_price
            weekend_markup_applied = Decimal("0")
        
        # Step 2: Apply intraday discount
        discount_bucket, discount_percent = self.get_current_discount_bucket(policy, current_time)
        
        if discount_percent > 0:
            final_price = day_price * (1 - discount_percent / 100)
            discount_applied = discount_percent
        else:
            final_price = day_price
            discount_applied = Decimal("0")
        
        # Round to 2 decimal places
        final_price = final_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        day_price = day_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        return DailyPrice(
            date=check_date,
            base_price=base_price,
            day_price=day_price,
            final_price=final_price,
            is_weekend=is_weekend,
            weekend_markup_applied=weekend_markup_applied,
            discount_applied=discount_applied,
            discount_bucket=discount_bucket,
            currency=policy.currency or "SAR"
        )
    
    def generate_price_calendar(
        self,
        unit_id: str,
        start_date: date,
        end_date: date,
        include_discounts: bool = False,
        current_time: Optional[datetime] = None
    ) -> Optional[PriceCalendar]:
        """
        Generate a price calendar for a unit over a date range.
        
        This is the "calendar generation" mode - computes prices for all days.
        For pushing to Channex, set include_discounts=False to get base rates.
        For real-time booking display, set include_discounts=True.
        
        Args:
            unit_id: The unit to generate prices for
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            include_discounts: If True, applies current intraday discount
                              If False, uses 0 discount (for channel push)
            current_time: Time to use for discount calculation (if include_discounts=True)
        
        Returns:
            PriceCalendar with all computed daily prices, or None if no policy
        """
        policy = self.get_policy_for_unit(unit_id)
        if not policy:
            return None
        
        prices = []
        current_date = start_date
        
        # For channel push, we don't apply intraday discounts
        if not include_discounts:
            # Create a dummy time before 16:00 to get 0 discount
            tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
            calc_time = datetime(2020, 1, 1, 10, 0, 0, tzinfo=tz)  # 10 AM, no discount
        else:
            calc_time = current_time
        
        while current_date <= end_date:
            day_price = self.compute_day_price(policy, current_date, calc_time)
            prices.append(day_price)
            current_date += timedelta(days=1)
        
        return PriceCalendar(
            unit_id=unit_id,
            start_date=start_date,
            end_date=end_date,
            prices=prices,
            policy_snapshot={
                "base_weekday_price": str(policy.base_weekday_price),
                "weekend_markup_percent": str(policy.weekend_markup_percent),
                "discount_16_percent": str(policy.discount_16_percent),
                "discount_21_percent": str(policy.discount_21_percent),
                "discount_23_percent": str(policy.discount_23_percent),
                "weekend_days": policy.weekend_days,
                "timezone": policy.timezone,
                "currency": policy.currency
            },
            generated_at=datetime.utcnow(),
            timezone=policy.timezone or "Asia/Riyadh"
        )
    
    def get_realtime_price(
        self,
        unit_id: str,
        check_date: date = None
    ) -> Optional[DailyPrice]:
        """
        Get the current real-time price for a unit (with active discount applied).
        
        This is what should be shown to customers making a same-day booking.
        
        Args:
            unit_id: The unit to get price for
            check_date: Date to price (defaults to today in unit's timezone)
        
        Returns:
            DailyPrice with current discount applied, or None if no policy
        """
        policy = self.get_policy_for_unit(unit_id)
        if not policy:
            return None
        
        tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
        now = datetime.now(tz)
        
        if check_date is None:
            check_date = now.date()
        
        return self.compute_day_price(policy, check_date, now)
    
    def compute_booking_total(
        self,
        unit_id: str,
        check_in: date,
        check_out: date,
        apply_realtime_discount_for_today: bool = True
    ) -> Optional[Dict]:
        """
        Compute total price for a booking (multi-night stay).
        
        Args:
            unit_id: The unit to book
            check_in: Check-in date
            check_out: Check-out date (exclusive, guest leaves this day)
            apply_realtime_discount_for_today: If True and check_in is today,
                                               apply current intraday discount
        
        Returns:
            Dictionary with breakdown and total, or None if no policy
        """
        policy = self.get_policy_for_unit(unit_id)
        if not policy:
            return None
        
        tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
        now = datetime.now(tz)
        today = now.date()
        
        nights = []
        total = Decimal("0")
        current_date = check_in
        
        while current_date < check_out:
            # Apply discount only for today if enabled
            if apply_realtime_discount_for_today and current_date == today:
                day_price = self.compute_day_price(policy, current_date, now)
            else:
                # No discount for future dates
                morning_time = datetime(2020, 1, 1, 10, 0, 0, tzinfo=tz)
                day_price = self.compute_day_price(policy, current_date, morning_time)
            
            nights.append({
                "date": current_date.isoformat(),
                "price": str(day_price.final_price),
                "is_weekend": day_price.is_weekend,
                "discount_applied": str(day_price.discount_applied) if day_price.discount_applied > 0 else None
            })
            total += day_price.final_price
            current_date += timedelta(days=1)
        
        return {
            "unit_id": unit_id,
            "check_in": check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "num_nights": len(nights),
            "nights": nights,
            "total": str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "currency": policy.currency or "SAR"
        }
    
    def get_prices_for_channel_push(
        self,
        unit_id: str,
        days_ahead: int = 365
    ) -> List[Dict]:
        """
        Get prices formatted for pushing to Channex.
        
        This generates base rates without intraday discounts.
        Channex expects: date, rate, min_stay, etc.
        
        Args:
            unit_id: The unit to get prices for
            days_ahead: Number of days to generate (default 365)
        
        Returns:
            List of dicts suitable for Channex ARI update
        """
        policy = self.get_policy_for_unit(unit_id)
        if not policy:
            return []
        
        tz = ZoneInfo(policy.timezone or "Asia/Riyadh")
        today = datetime.now(tz).date()
        end_date = today + timedelta(days=days_ahead)
        
        calendar = self.generate_price_calendar(
            unit_id=unit_id,
            start_date=today,
            end_date=end_date,
            include_discounts=False  # Base rates for channels
        )
        
        if not calendar:
            return []
        
        return [
            {
                "date": price.date.isoformat(),
                "rate": float(price.day_price),  # Day price (with weekend markup, no discount)
                "currency": price.currency,
                "is_weekend": price.is_weekend
            }
            for price in calendar.prices
        ]


def get_pricing_engine(db: Session) -> PricingEngine:
    """Factory function to get a pricing engine instance"""
    return PricingEngine(db)
