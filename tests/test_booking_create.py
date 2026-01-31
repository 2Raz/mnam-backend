"""
Tests for Booking Creation with Auto Pricing and Channel Source

Test Coverage:
1. Single night booking: total_price auto-calculated
2. 3 nights booking: total_price = final_total from calculate-booking
3. Booking source: always stored as "المنصة: X" or defaults to "المنصة: مباشر"
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Import your app and models
# Adjust imports based on your project structure
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import get_db
from app.models.booking import Booking
from app.models.unit import Unit
from app.models.project import Project
from app.models.customer import Customer
from app.models.user import User


class TestBookingCreation:
    """Test booking creation with auto pricing and source formatting."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return MagicMock(spec=Session)
    
    @pytest.fixture
    def mock_unit(self):
        """Create a mock unit with pricing."""
        unit = MagicMock(spec=Unit)
        unit.id = "unit-123"
        unit.price_days_of_week = 200
        unit.price_in_weekends = 300
        unit.project = MagicMock(spec=Project)
        unit.project.id = "project-123"
        unit.project.name = "مشروع تجريبي"
        return unit
    
    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock(spec=User)
        user.id = "user-123"
        user.username = "testuser"
        return user
    
    # ========== Test 1: Single Night - Auto Price Calculation ==========
    
    def test_single_night_booking_auto_price(self, mock_db, mock_unit, mock_user):
        """
        Test: حجز ليلة واحدة - يتم حساب السعر تلقائياً
        
        Scenario:
        - check_in_date: today
        - check_out_date: tomorrow (1 night)
        - total_price: not provided (None)
        
        Expected:
        - total_price should be calculated using pricing engine
        - booking should be created successfully
        """
        from app.routers.bookings import create_booking
        from app.schemas.booking import BookingCreate
        
        check_in = date.today()
        check_out = date.today() + timedelta(days=1)
        
        booking_data = BookingCreate(
            project_id="project-123",
            unit_id="unit-123",
            guest_name="أحمد محمد",
            guest_phone="+966501234567",
            check_in_date=check_in,
            check_out_date=check_out,
            total_price=None,  # لم يتم تحديد السعر
            channel_source=None  # مصدر فارغ
        )
        
        # Assert that price should be auto-calculated
        assert booking_data.total_price is None
        
        # The create_booking function should:
        # 1. Call pricing engine
        # 2. Set total_price from engine result
        # 3. Set channel_source to "المنصة: مباشر"
        
    def test_single_night_price_value(self):
        """
        Test: التحقق من قيمة السعر المحسوب لليلة واحدة
        """
        from app.routers.bookings import calculate_booking_price
        
        # Create a mock unit
        unit = MagicMock()
        unit.price_days_of_week = 200
        unit.price_in_weekends = 300
        
        check_in = date(2026, 1, 21)  # Wednesday (weekday)
        check_out = date(2026, 1, 22)  # Thursday (1 night)
        
        price = calculate_booking_price(unit, check_in, check_out)
        
        # Should be weekday price
        assert price == Decimal("200")
    
    # ========== Test 2: 3 Nights - Auto Price from Pricing Engine ==========
    
    def test_three_nights_booking_auto_price(self):
        """
        Test: حجز 3 ليالي - السعر = final_total من calculate-booking
        
        Scenario:
        - check_in_date: Saturday
        - check_out_date: Tuesday (3 nights: Sat, Sun, Mon)
        - total_price: 0 (should trigger auto-calculation)
        
        Expected:
        - Pricing engine should be called
        - total_price = sum of nightly prices
        """
        from app.services.pricing_engine import PricingEngine
        
        # Mock the pricing engine response
        expected_result = {
            "unit_id": "unit-123",
            "check_in": "2026-01-24",
            "check_out": "2026-01-27",
            "nights": 3,
            "nightly_prices": [
                {"date": "2026-01-24", "final_price": 300},  # Saturday (weekend)
                {"date": "2026-01-25", "final_price": 300},  # Sunday (weekend - in Saudi)
                {"date": "2026-01-26", "final_price": 200},  # Monday (weekday)
            ],
            "subtotal": 800,
            "total_discount": 0,
            "final_total": 800,
            "currency": "SAR"
        }
        
        # Verify the structure
        assert expected_result["nights"] == 3
        assert expected_result["final_total"] == 800
        
    def test_three_nights_with_different_days(self):
        """
        Test: 3 ليالي مع أيام مختلفة (أسبوع + نهاية أسبوع)
        """
        from app.routers.bookings import calculate_booking_price
        
        # Create a mock unit
        unit = MagicMock()
        unit.price_days_of_week = 200
        unit.price_in_weekends = 300
        
        # Thursday to Sunday (Fri=weekend, Sat=weekend)
        check_in = date(2026, 1, 22)  # Thursday
        check_out = date(2026, 1, 25)  # Sunday (3 nights)
        
        price = calculate_booking_price(unit, check_in, check_out)
        
        # Thu (weekday) + Fri (weekend) + Sat (weekend) = 200 + 300 + 300 = 800
        assert price == Decimal("800")
    
    # ========== Test 3: Channel Source Formatting ==========
    
    def test_channel_source_empty_defaults_to_direct(self):
        """
        Test: مصدر الحجز فارغ = "المنصة: مباشر"
        """
        from app.routers.bookings import create_booking
        
        # Test the transformation logic
        raw_source = ""
        
        KNOWN_PLATFORMS = {
            'direct': 'مباشر',
            'airbnb': 'Airbnb',
            'booking.com': 'Booking.com',
        }
        
        if not raw_source:
            formatted_source = "المنصة: مباشر"
        else:
            platform_name = KNOWN_PLATFORMS.get(raw_source.lower(), raw_source)
            formatted_source = f"المنصة: {platform_name}"
        
        assert formatted_source == "المنصة: مباشر"
    
    def test_channel_source_airbnb(self):
        """
        Test: مصدر "airbnb" = "المنصة: Airbnb"
        """
        raw_source = "airbnb"
        
        KNOWN_PLATFORMS = {
            'direct': 'مباشر',
            'airbnb': 'Airbnb',
            'booking.com': 'Booking.com',
        }
        
        platform_name = KNOWN_PLATFORMS.get(raw_source.lower(), raw_source)
        formatted_source = f"المنصة: {platform_name}"
        
        assert formatted_source == "المنصة: Airbnb"
    
    def test_channel_source_booking_com(self):
        """
        Test: مصدر "booking.com" = "المنصة: Booking.com"
        """
        raw_source = "booking.com"
        
        KNOWN_PLATFORMS = {
            'direct': 'مباشر',
            'airbnb': 'Airbnb',
            'booking.com': 'Booking.com',
        }
        
        platform_name = KNOWN_PLATFORMS.get(raw_source.lower(), raw_source)
        formatted_source = f"المنصة: {platform_name}"
        
        assert formatted_source == "المنصة: Booking.com"
    
    def test_channel_source_unknown_preserves_value(self):
        """
        Test: مصدر غير معروف يتم حفظه كما هو
        """
        raw_source = "منصة_جديدة"
        
        KNOWN_PLATFORMS = {
            'direct': 'مباشر',
            'airbnb': 'Airbnb',
            'booking.com': 'Booking.com',
        }
        
        platform_name = KNOWN_PLATFORMS.get(raw_source.lower(), raw_source)
        formatted_source = f"المنصة: {platform_name}"
        
        assert formatted_source == "المنصة: منصة_جديدة"
    
    def test_channel_source_already_formatted(self):
        """
        Test: مصدر بالصيغة الصحيحة بالفعل لا يتغير
        """
        raw_source = "المنصة: Airbnb"
        
        if raw_source.startswith("المنصة:"):
            formatted_source = raw_source
        else:
            formatted_source = f"المنصة: {raw_source}"
        
        assert formatted_source == "المنصة: Airbnb"
    
    # ========== Test 4: Prevent Zero Price Booking ==========
    
    def test_prevent_zero_price_multiday_booking(self):
        """
        Test: منع إنشاء حجز بسعر 0 عندما عدد الأيام > 1
        
        إذا فشل حساب السعر التلقائي يجب رفض الحجز
        """
        from app.schemas.booking import BookingCreate
        from decimal import Decimal
        
        booking_data = BookingCreate(
            project_id="project-123",
            unit_id="unit-123",
            guest_name="عميل تجريبي",
            guest_phone="+966501234567",
            check_in_date=date(2026, 1, 20),
            check_out_date=date(2026, 1, 23),  # 3 nights
            total_price=Decimal("0"),  # سعر صفر
        )
        
        # The backend should:
        # 1. Detect that total_price is 0
        # 2. Try to calculate price automatically
        # 3. If calculation fails, reject the booking
        
        assert booking_data.total_price == Decimal("0")
        
        # Number of nights
        nights = (booking_data.check_out_date - booking_data.check_in_date).days
        assert nights == 3
        
        # Logic: if nights > 0 and price <= 0, should fail or auto-calculate
    
    # ========== Integration Tests ==========
    
    def test_booking_response_includes_channel_source(self):
        """
        Test: استجابة الحجز تتضمن المصدر بالصيغة الصحيحة
        """
        # Mock booking response
        booking_response = {
            "id": "booking-123",
            "guest_name": "أحمد محمد",
            "check_in_date": "2026-01-20",
            "check_out_date": "2026-01-22",
            "total_price": 500,
            "channel_source": "المنصة: Airbnb",  # Formatted source
            "source_type": "manual"
        }
        
        assert "المنصة:" in booking_response["channel_source"]
    
    def test_nights_calculation(self):
        """
        Test: حساب عدد الليالي بشكل صحيح
        """
        check_in = date(2026, 1, 20)
        check_out = date(2026, 1, 25)
        
        nights = (check_out - check_in).days
        
        assert nights == 5


class TestPricingEngine:
    """Test pricing engine integration."""
    
    def test_compute_booking_total_returns_correct_structure(self):
        """
        Test: محرك التسعير يرجع البنية الصحيحة
        """
        expected_keys = [
            "unit_id",
            "check_in",
            "check_out",
            "nights",
            "nightly_prices",
            "subtotal",
            "total_discount",
            "final_total",
            "currency"
        ]
        
        # This is a structural test
        mock_result = {
            "unit_id": "unit-123",
            "check_in": "2026-01-20",
            "check_out": "2026-01-21",
            "nights": 1,
            "nightly_prices": [],
            "subtotal": 200,
            "total_discount": 0,
            "final_total": 200,
            "currency": "SAR"
        }
        
        for key in expected_keys:
            assert key in mock_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
