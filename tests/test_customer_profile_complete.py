"""
Tests for Customer Profile Completion Logic

Test Coverage:
1. name+phone exist, gender null, notes null => is_profile_complete = True
2. name missing or phone missing => is_profile_complete = False
3. created-from-booking: is_profile_complete=false then update name/phone => becomes True even with gender null
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

# Import your models
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.customer import Customer, GenderEnum


class TestCustomerProfileComplete:
    """Test profile completion logic."""
    
    def test_name_and_phone_is_complete(self):
        """
        Test: name+phone موجودة, gender null, notes null => is_profile_complete = True
        """
        customer = Customer(
            id="test-123",
            name="أحمد محمد",
            phone="0501234567",
            email=None,
            gender=None,
            notes=None
        )
        
        # Check profile completion
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True
        
    def test_name_and_phone_with_email_is_complete(self):
        """
        Test: name+phone+email => is_profile_complete = True
        """
        customer = Customer(
            id="test-124",
            name="محمد سعود",
            phone="0509876543",
            email="test@example.com",
            gender=None,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True
        
    def test_name_and_phone_with_gender_is_complete(self):
        """
        Test: name+phone+gender => is_profile_complete = True
        """
        customer = Customer(
            id="test-125",
            name="فاطمة علي",
            phone="0551234567",
            email=None,
            gender=GenderEnum.FEMALE,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True
        
    def test_full_profile_is_complete(self):
        """
        Test: All fields filled => is_profile_complete = True
        """
        customer = Customer(
            id="test-126",
            name="خالد الشمري",
            phone="0554321987",
            email="khalid@example.com",
            gender=GenderEnum.MALE,
            notes="عميل مميز"
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True
    
    def test_missing_name_is_incomplete(self):
        """
        Test: name ناقص => is_profile_complete = False
        """
        customer = Customer(
            id="test-127",
            name="",  # Empty name
            phone="0501234567",
            email="test@example.com",
            gender=GenderEnum.MALE,
            notes="ملاحظة"
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_short_name_is_incomplete(self):
        """
        Test: اسم قصير (أقل من حرفين) => is_profile_complete = False
        """
        customer = Customer(
            id="test-128",
            name="أ",  # Only 1 character
            phone="0501234567",
            email=None,
            gender=None,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_missing_phone_is_incomplete(self):
        """
        Test: phone ناقص => is_profile_complete = False
        """
        customer = Customer(
            id="test-129",
            name="عبدالله محمد",
            phone="",  # Empty phone
            email="test@example.com",
            gender=GenderEnum.MALE,
            notes="ملاحظة"
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_short_phone_is_incomplete(self):
        """
        Test: رقم جوال قصير (أقل من 9) => is_profile_complete = False
        """
        customer = Customer(
            id="test-130",
            name="سعود الدوسري",
            phone="050123",  # Too short
            email=None,
            gender=None,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_null_name_is_incomplete(self):
        """
        Test: name = None => is_profile_complete = False
        """
        customer = Customer(
            id="test-131",
            name=None,
            phone="0501234567",
            email=None,
            gender=None,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_null_phone_is_incomplete(self):
        """
        Test: phone = None => is_profile_complete = False
        """
        customer = Customer(
            id="test-132",
            name="محمد علي",
            phone=None,
            email=None,
            gender=None,
            notes=None
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False


class TestCustomerCreatedFromBooking:
    """Test created-from-booking scenario."""
    
    def test_booking_created_customer_initially_incomplete(self):
        """
        Test: عميل تم إنشاؤه من حجز = is_profile_complete بناءً على البيانات
        
        عند الإنشاء من حجز، إذا كان name+phone كاملين، يجب أن يكون complete
        """
        # Simulate customer created from booking with short/empty name
        customer = Customer(
            id="booking-customer-1",
            name="أ",  # اسم قصير جاء من الحجز
            phone="0501234567",
            gender=GenderEnum.MALE,
            booking_count=1,
            is_profile_complete=False  # Set initially
        )
        
        # Update the status
        customer.update_profile_complete_status()
        
        # Still incomplete because name is too short
        assert customer.is_profile_complete == False
        
    def test_booking_customer_becomes_complete_after_name_update(self):
        """
        Test: عميل من حجز ثم تحديث الاسم => يصبح مكتمل حتى لو gender null
        """
        customer = Customer(
            id="booking-customer-2",
            name="أ",  # Initially short
            phone="0501234567",
            gender=None,  # No gender
            notes=None,  # No notes
            booking_count=1,
            is_profile_complete=False
        )
        
        # Verify initially incomplete
        customer.update_profile_complete_status()
        assert customer.is_profile_complete == False
        
        # Simulate update (user completes the profile)
        customer.name = "أحمد محمد الشمري"
        customer.update_profile_complete_status()
        
        # Now complete! (gender and notes are still None)
        assert customer.is_profile_complete == True
        assert customer.gender is None
        assert customer.notes is None
        
    def test_booking_customer_with_proper_data_is_complete(self):
        """
        Test: عميل من حجز ببيانات صحيحة من البداية = مكتمل
        """
        customer = Customer(
            id="booking-customer-3",
            name="محمد عبدالله",
            phone="0509876543",
            gender=None,
            notes=None,
            booking_count=1,
            is_profile_complete=False  # Initially set to false
        )
        
        # Recalculate
        customer.update_profile_complete_status()
        
        # Should be complete because name >= 2 chars and phone >= 9 chars
        assert customer.is_profile_complete == True
        
    def test_update_phone_makes_complete(self):
        """
        Test: تحديث رقم الجوال => يصبح مكتمل
        """
        customer = Customer(
            id="booking-customer-4",
            name="سعود عبدالله",
            phone="050",  # Initially too short
            gender=GenderEnum.MALE,
            is_profile_complete=False
        )
        
        customer.update_profile_complete_status()
        assert customer.is_profile_complete == False
        
        # Update phone
        customer.phone = "0501234567"
        customer.update_profile_complete_status()
        
        assert customer.is_profile_complete == True


class TestGenderAndNotesDoNotAffectCompletion:
    """Verify that gender and notes don't affect is_profile_complete."""
    
    def test_gender_null_does_not_affect_completion(self):
        """
        Test: gender = None لا يؤثر على الاكتمال
        """
        customer_with_gender = Customer(
            id="gender-test-1",
            name="أحمد محمد",
            phone="0501234567",
            gender=GenderEnum.MALE
        )
        
        customer_without_gender = Customer(
            id="gender-test-2",
            name="أحمد محمد",
            phone="0501234567",
            gender=None
        )
        
        assert customer_with_gender.check_profile_complete() == True
        assert customer_without_gender.check_profile_complete() == True
        
    def test_notes_null_does_not_affect_completion(self):
        """
        Test: notes = None لا يؤثر على الاكتمال
        """
        customer_with_notes = Customer(
            id="notes-test-1",
            name="محمد علي",
            phone="0509876543",
            notes="ملاحظات هامة"
        )
        
        customer_without_notes = Customer(
            id="notes-test-2",
            name="محمد علي",
            phone="0509876543",
            notes=None
        )
        
        assert customer_with_notes.check_profile_complete() == True
        assert customer_without_notes.check_profile_complete() == True
        
    def test_email_null_does_not_affect_completion(self):
        """
        Test: email = None لا يؤثر على الاكتمال
        """
        customer_with_email = Customer(
            id="email-test-1",
            name="خالد سعود",
            phone="0551234567",
            email="test@example.com"
        )
        
        customer_without_email = Customer(
            id="email-test-2",
            name="خالد سعود",
            phone="0551234567",
            email=None
        )
        
        assert customer_with_email.check_profile_complete() == True
        assert customer_without_email.check_profile_complete() == True


class TestEdgeCases:
    """Test edge cases."""
    
    def test_whitespace_only_name_is_incomplete(self):
        """
        Test: اسم مكون من مسافات فقط = ناقص
        """
        customer = Customer(
            id="edge-1",
            name="   ",  # Only whitespace
            phone="0501234567"
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_whitespace_only_phone_is_incomplete(self):
        """
        Test: رقم جوال مكون من مسافات فقط = ناقص
        """
        customer = Customer(
            id="edge-2",
            name="أحمد محمد",
            phone="         "  # Only whitespace
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == False
        
    def test_exactly_2_char_name_is_complete(self):
        """
        Test: اسم من حرفين بالضبط = مكتمل
        """
        customer = Customer(
            id="edge-3",
            name="أب",
            phone="0501234567"
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True
        
    def test_exactly_9_char_phone_is_complete(self):
        """
        Test: رقم جوال من 9 أرقام بالضبط = مكتمل
        """
        customer = Customer(
            id="edge-4",
            name="أحمد محمد",
            phone="501234567"  # 9 digits
        )
        
        is_complete = customer.check_profile_complete()
        
        assert is_complete == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
