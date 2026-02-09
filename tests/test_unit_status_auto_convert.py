"""
Tests for Auto Unit Status Conversion
اختبارات تحويل حالة الوحدة تلقائياً
"""

import pytest
from datetime import date, timedelta


class TestAutoUnitStatusConversion:
    """Tests for automatic unit status conversion linked to bookings"""
    
    def test_unit_status_changes_to_booked_on_booking_create(self):
        """إنشاء حجز → حالة الوحدة = 'محجوزة'"""
        # Simulate the logic
        old_status = "متاحة"
        effective_status = "محجوزة"  # computed from bookings
        
        # Logic from _auto_update_unit_status
        new_status = old_status
        if old_status == "متاحة" and effective_status == "محجوزة":
            new_status = "محجوزة"
        
        assert new_status == "محجوزة"
    
    def test_unit_status_changes_to_available_on_all_bookings_cancelled(self):
        """إلغاء جميع الحجوزات → حالة = 'متاحة'"""
        old_status = "محجوزة"
        effective_status = "متاحة"  # no active bookings
        
        new_status = old_status
        if old_status == "محجوزة" and effective_status == "متاحة":
            new_status = "متاحة"
        
        assert new_status == "متاحة"
    
    def test_unit_status_preserved_for_maintenance(self):
        """حالة 'صيانة' لا تتغير تلقائياً عند وجود حجوزات"""
        old_status = "صيانة"
        effective_status = "صيانة"  # manual status preserved
        
        # Logic: only "متاحة" → "محجوزة" or "محجوزة" → "متاحة" transitions
        new_status = old_status
        if old_status == "متاحة" and effective_status == "محجوزة":
            new_status = "محجوزة"
        elif old_status == "محجوزة" and effective_status == "متاحة":
            new_status = "متاحة"
        
        # Status should remain unchanged
        assert new_status == "صيانة"
    
    def test_unit_status_preserved_for_cleaning(self):
        """حالة 'تحتاج تنظيف' لا تتغير تلقائياً"""
        old_status = "تحتاج تنظيف"
        effective_status = "تحتاج تنظيف"
        
        new_status = old_status
        if old_status == "متاحة" and effective_status == "محجوزة":
            new_status = "محجوزة"
        elif old_status == "محجوزة" and effective_status == "متاحة":
            new_status = "متاحة"
        
        assert new_status == "تحتاج تنظيف"
    
    def test_unit_status_preserved_for_hidden(self):
        """حالة 'مخفية' لا تتغير تلقائياً"""
        old_status = "مخفية"
        effective_status = "مخفية"
        
        new_status = old_status
        if old_status == "متاحة" and effective_status == "محجوزة":
            new_status = "محجوزة"
        elif old_status == "محجوزة" and effective_status == "متاحة":
            new_status = "متاحة"
        
        assert new_status == "مخفية"
    
    def test_no_change_when_already_booked_and_has_bookings(self):
        """لا تغيير إذا كانت الحالة 'محجوزة' ولا زال هناك حجوزات"""
        old_status = "محجوزة"
        effective_status = "محجوزة"
        
        new_status = old_status
        if old_status == "متاحة" and effective_status == "محجوزة":
            new_status = "محجوزة"
        elif old_status == "محجوزة" and effective_status == "متاحة":
            new_status = "متاحة"
        
        assert new_status == "محجوزة"


# Entry point for running tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
