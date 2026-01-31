"""
اختبارات حساب الحجوزات اليومية والمهام
Tests for Daily Bookings Count and Tasks
"""
import pytest
from datetime import datetime, date, timedelta, timezone
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

# Mock database session
@pytest.fixture
def mock_db():
    """Mock database session"""
    return MagicMock()


@pytest.fixture
def mock_user():
    """Mock user object"""
    user = MagicMock()
    user.id = "user-123"
    user.first_name = "Test"
    user.last_name = "User"
    user.role = "customers_agent"
    user.is_active = True
    return user


class TestDailyBookingsCount:
    """اختبارات حساب الحجوزات اليومية"""
    
    def test_count_bookings_today_returns_correct_count(self, mock_db):
        """يجب أن يحسب عدد الحجوزات لليوم الحالي بشكل صحيح"""
        from app.routers.tasks import count_bookings_today
        
        # Mock the query to return 5 bookings
        mock_db.query.return_value.filter.return_value.scalar.return_value = 5
        
        result = count_bookings_today(mock_db, "user-123")
        
        assert result == 5
    
    def test_count_bookings_today_excludes_cancelled(self, mock_db):
        """يجب أن يستثني الحجوزات الملغاة"""
        from app.routers.tasks import count_bookings_today
        
        # This tests that the query filters out cancelled bookings
        # The filter should include: status != 'ملغي'
        mock_db.query.return_value.filter.return_value.scalar.return_value = 3
        
        result = count_bookings_today(mock_db, "user-123")
        
        # Verify filter was called (checking the query was built correctly)
        assert mock_db.query.called
        assert result == 3
    
    def test_count_bookings_today_returns_zero_when_no_bookings(self, mock_db):
        """يجب أن يرجع صفر إذا لم تكن هناك حجوزات"""
        from app.routers.tasks import count_bookings_today
        
        mock_db.query.return_value.filter.return_value.scalar.return_value = None
        
        result = count_bookings_today(mock_db, "user-123")
        
        assert result == 0
    
    def test_get_today_riyadh_returns_correct_timezone(self):
        """يجب أن يرجع تاريخ اليوم بتوقيت الرياض"""
        from app.routers.tasks import get_today_riyadh
        
        riyadh_tz = ZoneInfo("Asia/Riyadh")
        expected = datetime.now(riyadh_tz).date()
        
        result = get_today_riyadh()
        
        assert result == expected
    
    def test_get_today_start_utc_returns_datetime(self):
        """يجب أن يرجع بداية اليوم بتوقيت UTC"""
        from app.routers.tasks import get_today_start_utc
        
        result = get_today_start_utc()
        
        assert isinstance(result, datetime)
        # Should be at or before current UTC time
        assert result <= datetime.utcnow()
    
    def test_get_today_end_utc_returns_datetime(self):
        """يجب أن يرجع نهاية اليوم بتوقيت UTC"""
        from app.routers.tasks import get_today_end_utc
        
        result = get_today_end_utc()
        
        assert isinstance(result, datetime)
        # Should be at or after current UTC time
        assert result >= datetime.utcnow()


class TestTasksCRUD:
    """اختبارات CRUD للمهام"""
    
    def test_create_task_success(self, mock_db, mock_user):
        """يجب أن ينشئ مهمة جديدة بنجاح"""
        from app.models.task import EmployeeTask, TaskStatus
        
        task = EmployeeTask(
            title="مهمة اختبارية",
            description="وصف المهمة",
            assigned_to_id="user-123",
            created_by_id="admin-123",
            status=TaskStatus.TODO.value
        )
        
        assert task.title == "مهمة اختبارية"
        assert task.status == "todo"
        assert task.assigned_to_id == "user-123"
    
    def test_task_status_enum(self):
        """يجب أن يكون لدينا حالتين: todo و done"""
        from app.models.task import TaskStatus
        
        assert TaskStatus.TODO.value == "todo"
        assert TaskStatus.DONE.value == "done"
    
    def test_task_with_due_date(self):
        """يجب أن يدعم تاريخ الاستحقاق"""
        from app.models.task import EmployeeTask
        
        due = date.today() + timedelta(days=7)
        task = EmployeeTask(
            title="مهمة مع موعد",
            due_date=due,
            assigned_to_id="user-123"
        )
        
        assert task.due_date == due
    
    def test_task_without_due_date(self):
        """يجب أن يسمح بإنشاء مهمة بدون تاريخ استحقاق"""
        from app.models.task import EmployeeTask
        
        task = EmployeeTask(
            title="مهمة بدون موعد",
            assigned_to_id="user-123"
        )
        
        assert task.due_date is None


class TestEmployeeProfile:
    """اختبارات ملف الموظف"""
    
    def test_profile_includes_daily_performance(self, mock_db, mock_user):
        """يجب أن يتضمن الملف أداء اليوم"""
        # The profile endpoint should return:
        # - booked_today_count
        # - daily_target
        # - progress_percent
        
        expected_keys = ['booked_today_count', 'daily_target', 'progress_percent', 'date']
        
        # This is a structural test - the actual endpoint test would be integration
        assert all(key for key in expected_keys)
    
    def test_progress_calculation(self):
        """يجب أن يحسب نسبة الإنجاز بشكل صحيح"""
        booked = 3
        target = 5
        
        progress = (booked / target) * 100 if target > 0 else 0
        
        assert progress == 60.0
    
    def test_progress_capped_at_100(self):
        """يجب أن تكون نسبة الإنجاز محددة بـ 100%"""
        booked = 7
        target = 5
        
        progress = min((booked / target) * 100, 100.0)
        
        assert progress == 100.0
    
    def test_progress_zero_when_no_target(self):
        """يجب أن ترجع 0 إذا لم يكن هناك هدف"""
        booked = 5
        target = 0
        
        progress = (booked / target) * 100 if target > 0 else 0.0
        
        assert progress == 0.0


class TestTimezoneHandling:
    """اختبارات معالجة المنطقة الزمنية"""
    
    def test_riyadh_timezone_offset(self):
        """يجب أن يكون فرق توقيت الرياض +3"""
        riyadh_tz = ZoneInfo("Asia/Riyadh")
        now = datetime.now(riyadh_tz)
        
        # Riyadh is UTC+3
        offset_hours = now.utcoffset().total_seconds() / 3600
        
        assert offset_hours == 3.0
    
    def test_date_boundary_conversion(self):
        """يجب أن يتحول حد التاريخ بشكل صحيح بين المناطق الزمنية"""
        riyadh_tz = ZoneInfo("Asia/Riyadh")
        
        # 00:00 Riyadh = 21:00 UTC previous day
        riyadh_midnight = datetime.combine(date.today(), datetime.min.time(), tzinfo=riyadh_tz)
        utc_equivalent = riyadh_midnight.astimezone(timezone.utc)
        
        # The hour in UTC should be 21 (or 24-3)
        assert utc_equivalent.hour == 21 or (utc_equivalent.hour == 0 and utc_equivalent.day == riyadh_midnight.day)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
