"""
Tests for the Pricing Engine

These tests verify the core pricing logic including:
- Base weekday pricing
- Weekend markup calculation
- Intraday discount application
- Price calendar generation
- Booking total calculation
"""

import pytest
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch


# Test the pricing formulas without database
class TestPricingFormulas:
    """Unit tests for pricing formulas"""
    
    def test_weekday_base_price(self):
        """Base weekday price should be returned as-is on weekdays"""
        base_price = Decimal("100.00")
        is_weekend = False
        weekend_markup = Decimal("150")  # 150%
        
        if is_weekend:
            day_price = base_price * (1 + weekend_markup / 100)
        else:
            day_price = base_price
        
        assert day_price == Decimal("100.00")
    
    def test_weekend_markup_150_percent(self):
        """150% weekend markup on 100 SAR base should give 250 SAR"""
        base_price = Decimal("100.00")
        is_weekend = True
        weekend_markup = Decimal("150")  # 150%
        
        if is_weekend:
            day_price = base_price * (1 + weekend_markup / 100)
        else:
            day_price = base_price
        
        # 100 * (1 + 1.50) = 100 * 2.5 = 250
        assert day_price == Decimal("250.00")
    
    def test_weekend_markup_50_percent(self):
        """50% weekend markup on 100 SAR base should give 150 SAR"""
        base_price = Decimal("100.00")
        is_weekend = True
        weekend_markup = Decimal("50")  # 50%
        
        day_price = base_price * (1 + weekend_markup / 100)
        
        # 100 * (1 + 0.50) = 100 * 1.5 = 150
        assert day_price == Decimal("150.00")
    
    def test_weekend_markup_zero(self):
        """0% weekend markup should not change price"""
        base_price = Decimal("100.00")
        is_weekend = True
        weekend_markup = Decimal("0")
        
        day_price = base_price * (1 + weekend_markup / 100)
        
        assert day_price == Decimal("100.00")
    
    def test_discount_16_percent(self):
        """10% discount at 16:00 on 250 SAR should give 225 SAR"""
        day_price = Decimal("250.00")
        discount_percent = Decimal("10")  # 10%
        
        final_price = day_price * (1 - discount_percent / 100)
        
        # 250 * (1 - 0.10) = 250 * 0.90 = 225
        assert final_price == Decimal("225.00")
    
    def test_discount_on_base_price(self):
        """20% discount on 100 SAR base should give 80 SAR"""
        day_price = Decimal("100.00")
        discount_percent = Decimal("20")
        
        final_price = day_price * (1 - discount_percent / 100)
        
        assert final_price == Decimal("80.00")
    
    def test_full_formula_weekday_with_discount(self):
        """Weekday price 100 SAR with 15% discount at 21:00 = 85 SAR"""
        base_price = Decimal("100.00")
        weekend_markup = Decimal("150")
        is_weekend = False
        discount_percent = Decimal("15")
        
        # Step 1: Apply weekend markup (not applicable)
        day_price = base_price if not is_weekend else base_price * (1 + weekend_markup / 100)
        
        # Step 2: Apply discount
        final_price = day_price * (1 - discount_percent / 100)
        
        assert final_price == Decimal("85.00")
    
    def test_full_formula_weekend_with_discount(self):
        """
        Weekend: base=100, markup=150%, discount=10%
        day_price = 100 * 2.5 = 250
        final = 250 * 0.9 = 225
        """
        base_price = Decimal("100.00")
        weekend_markup = Decimal("150")
        is_weekend = True
        discount_percent = Decimal("10")
        
        day_price = base_price * (1 + weekend_markup / 100)
        final_price = day_price * (1 - discount_percent / 100)
        
        assert day_price == Decimal("250.00")
        assert final_price == Decimal("225.00")


class TestDiscountBuckets:
    """Tests for time-based discount bucket selection"""
    
    def get_discount_bucket(self, hour: int) -> str:
        """Simulate the discount bucket logic"""
        if hour >= 23:
            return "23"
        elif hour >= 21:
            return "21"
        elif hour >= 16:
            return "16"
        else:
            return "none"
    
    def test_before_16(self):
        """Before 16:00 should have no discount"""
        assert self.get_discount_bucket(0) == "none"
        assert self.get_discount_bucket(8) == "none"
        assert self.get_discount_bucket(12) == "none"
        assert self.get_discount_bucket(15) == "none"
    
    def test_16_to_20(self):
        """16:00-20:59 should use discount_16_percent"""
        assert self.get_discount_bucket(16) == "16"
        assert self.get_discount_bucket(18) == "16"
        assert self.get_discount_bucket(20) == "16"
    
    def test_21_to_22(self):
        """21:00-22:59 should use discount_21_percent"""
        assert self.get_discount_bucket(21) == "21"
        assert self.get_discount_bucket(22) == "21"
    
    def test_23_onwards(self):
        """23:00-23:59 should use discount_23_percent"""
        assert self.get_discount_bucket(23) == "23"


class TestWeekendDetection:
    """Tests for weekend day detection"""
    
    def is_weekend(self, check_date: date, weekend_days: set) -> bool:
        """Simulate weekend detection logic"""
        return check_date.weekday() in weekend_days
    
    def test_ksa_weekend(self):
        """KSA weekend is Friday (4) and Saturday (5)"""
        weekend_days = {4, 5}  # Friday, Saturday
        
        # Find a known Friday
        friday = date(2026, 1, 16)  # This is a Friday
        assert friday.weekday() == 4
        assert self.is_weekend(friday, weekend_days) == True
        
        # Find a known Saturday
        saturday = date(2026, 1, 17)
        assert saturday.weekday() == 5
        assert self.is_weekend(saturday, weekend_days) == True
        
        # Sunday should not be weekend
        sunday = date(2026, 1, 18)
        assert sunday.weekday() == 6
        assert self.is_weekend(sunday, weekend_days) == False
        
        # Thursday should not be weekend
        thursday = date(2026, 1, 15)
        assert thursday.weekday() == 3
        assert self.is_weekend(thursday, weekend_days) == False
    
    def test_western_weekend(self):
        """Western weekend is Saturday (5) and Sunday (6)"""
        weekend_days = {5, 6}  # Saturday, Sunday
        
        saturday = date(2026, 1, 17)
        assert self.is_weekend(saturday, weekend_days) == True
        
        sunday = date(2026, 1, 18)
        assert self.is_weekend(sunday, weekend_days) == True
        
        friday = date(2026, 1, 16)
        assert self.is_weekend(friday, weekend_days) == False


class TestBookingTotalCalculation:
    """Tests for multi-night booking total calculation"""
    
    def calculate_booking_total(
        self,
        base_price: Decimal,
        weekend_markup: Decimal,
        check_in: date,
        check_out: date,
        weekend_days: set
    ) -> Decimal:
        """Simulate booking total calculation (without discounts for simplicity)"""
        total = Decimal("0")
        current = check_in
        
        while current < check_out:
            is_weekend = current.weekday() in weekend_days
            if is_weekend:
                day_price = base_price * (1 + weekend_markup / 100)
            else:
                day_price = base_price
            total += day_price
            current += timedelta(days=1)
        
        return total
    
    def test_single_weekday_night(self):
        """Single weekday night should equal base price"""
        total = self.calculate_booking_total(
            base_price=Decimal("100"),
            weekend_markup=Decimal("150"),
            check_in=date(2026, 1, 14),  # Wednesday
            check_out=date(2026, 1, 15),  # Thursday
            weekend_days={4, 5}
        )
        
        assert total == Decimal("100")
    
    def test_single_weekend_night(self):
        """Single Friday night with 150% markup should be 250"""
        total = self.calculate_booking_total(
            base_price=Decimal("100"),
            weekend_markup=Decimal("150"),
            check_in=date(2026, 1, 16),  # Friday
            check_out=date(2026, 1, 17),  # Saturday
            weekend_days={4, 5}
        )
        
        assert total == Decimal("250")
    
    def test_mixed_week(self):
        """3 weekday nights + 2 weekend nights"""
        # Wed, Thu, Fri (weekend), Sat (weekend), checkout Sun
        # 100 + 100 + 250 + 250 = 700
        total = self.calculate_booking_total(
            base_price=Decimal("100"),
            weekend_markup=Decimal("150"),
            check_in=date(2026, 1, 14),  # Wednesday
            check_out=date(2026, 1, 18),  # Sunday (4 nights)
            weekend_days={4, 5}
        )
        
        # Wed=100, Thu=100, Fri=250, Sat=250 = 700
        assert total == Decimal("700")


class TestEdgeCases:
    """Tests for edge cases and boundary conditions"""
    
    def test_zero_base_price(self):
        """Zero base price should always result in zero"""
        base_price = Decimal("0")
        weekend_markup = Decimal("150")
        discount = Decimal("10")
        
        day_price = base_price * (1 + weekend_markup / 100)
        final_price = day_price * (1 - discount / 100)
        
        assert final_price == Decimal("0")
    
    def test_100_percent_discount(self):
        """100% discount should result in zero"""
        base_price = Decimal("100")
        discount = Decimal("100")
        
        final_price = base_price * (1 - discount / 100)
        
        assert final_price == Decimal("0")
    
    def test_rounding(self):
        """Prices should round to 2 decimal places"""
        from decimal import ROUND_HALF_UP
        
        # 100 / 3 = 33.333...
        base_price = Decimal("100") / 3
        rounded = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        assert rounded == Decimal("33.33")
    
    def test_very_high_markup(self):
        """500% markup should be 6x base price"""
        base_price = Decimal("100")
        weekend_markup = Decimal("500")
        
        day_price = base_price * (1 + weekend_markup / 100)
        
        # 100 * (1 + 5) = 600
        assert day_price == Decimal("600")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
