"""
نماذج تتبع جلسات الموظفين والحضور
Employee Session and Attendance Tracking Models
"""
import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Integer, DateTime, Date, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class EmployeeSession(Base):
    """
    جلسات الموظفين
    يتتبع كل جلسة دخول للموظف في النظام
    """
    __tablename__ = "employee_sessions"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # الموظف
    employee_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # أوقات الجلسة
    login_at = Column(DateTime, nullable=False, default=datetime.utcnow)  # وقت بداية الجلسة
    logout_at = Column(DateTime, nullable=True)  # وقت نهاية الجلسة
    last_heartbeat = Column(DateTime, default=datetime.utcnow)  # آخر نبضة (كل دقيقة)
    
    # مدة الجلسة
    duration_minutes = Column(Integer, default=0)  # مدة الجلسة بالدقائق
    
    # حالة الجلسة
    is_active = Column(Boolean, default=True)  # هل الجلسة نشطة؟
    
    # معلومات إضافية
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # التاريخ
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # العلاقات
    employee = relationship("User", foreign_keys=[employee_id])
    
    def __repr__(self):
        return f"<Session {self.id[:8]} for {self.employee_id[:8]}>"
    
    @property
    def calculated_duration_minutes(self) -> int:
        """حساب مدة الجلسة بالدقائق"""
        end_time = self.logout_at or datetime.utcnow()
        delta = end_time - self.login_at
        return int(delta.total_seconds() / 60)
    
    def close_session(self):
        """إغلاق الجلسة"""
        self.logout_at = datetime.utcnow()
        self.duration_minutes = self.calculated_duration_minutes
        self.is_active = False


class EmployeeAttendance(Base):
    """
    سجل الحضور اليومي
    ملخص يومي لحضور كل موظف
    """
    __tablename__ = "employee_attendance"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # الموظف واليوم
    employee_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)  # تاريخ الحضور
    
    # أوقات الحضور
    first_login = Column(DateTime, nullable=True)  # أول تسجيل دخول اليوم
    last_logout = Column(DateTime, nullable=True)  # آخر تسجيل خروج
    last_activity = Column(DateTime, nullable=True)  # آخر نشاط
    
    # إحصائيات الجلسات
    total_sessions = Column(Integer, default=0)  # عدد الجلسات
    total_duration_minutes = Column(Integer, default=0)  # إجمالي الوقت بالدقائق
    
    # إحصائيات الأنشطة
    activities_count = Column(Integer, default=0)  # عدد الأنشطة
    
    # التواريخ
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint: موظف واحد + يوم واحد
    __table_args__ = (
        UniqueConstraint('employee_id', 'date', name='uq_employee_date'),
    )
    
    # العلاقات
    employee = relationship("User", foreign_keys=[employee_id])
    
    def __repr__(self):
        return f"<Attendance {self.employee_id[:8]} on {self.date}>"
    
    @property
    def formatted_duration(self) -> str:
        """تنسيق المدة الإجمالية"""
        hours = self.total_duration_minutes // 60
        minutes = self.total_duration_minutes % 60
        if hours > 0:
            return f"{hours}س {minutes}د"
        return f"{minutes}د"


# ثوابت النظام
OFFLINE_TIMEOUT_MINUTES = 5  # 5 دقائق = غير متصل
HEARTBEAT_INTERVAL_SECONDS = 60  # نبضة كل دقيقة
