"""
نموذج الإشعارات - Notification Model
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from ..database import Base


class NotificationType(str, enum.Enum):
    """أنواع الإشعارات"""
    # الحجوزات
    BOOKING_NEW = "booking_new"               # حجز جديد
    BOOKING_CANCELLED = "booking_cancelled"   # إلغاء حجز
    BOOKING_MODIFIED = "booking_modified"     # تعديل حجز
    BOOKING_CHECKIN = "booking_checkin"       # تسجيل وصول
    BOOKING_CHECKOUT = "booking_checkout"     # تسجيل مغادرة
    
    # الوحدات
    UNIT_NEEDS_CLEANING = "unit_needs_cleaning"   # تحتاج تنظيف
    UNIT_NEEDS_MAINTENANCE = "unit_needs_maintenance"  # تحتاج صيانة
    UNIT_STATUS_CHANGED = "unit_status_changed"   # تغيير حالة
    
    # المهام
    TASK_ASSIGNED = "task_assigned"           # مهمة جديدة
    TASK_DUE = "task_due"                     # مهمة مستحقة
    TASK_COMPLETED = "task_completed"         # مهمة مكتملة
    
    # العملاء
    CUSTOMER_VIP_ARRIVING = "customer_vip_arriving"  # عميل مميز قادم
    CUSTOMER_BANNED = "customer_banned"       # حظر عميل
    
    # النظام
    SYSTEM_ALERT = "system_alert"             # تنبيه نظام
    SYSTEM_UPDATE = "system_update"           # تحديث نظام


# تسميات أنواع الإشعارات بالعربية
NOTIFICATION_TYPE_LABELS = {
    NotificationType.BOOKING_NEW: "حجز جديد",
    NotificationType.BOOKING_CANCELLED: "إلغاء حجز",
    NotificationType.BOOKING_MODIFIED: "تعديل حجز",
    NotificationType.BOOKING_CHECKIN: "تسجيل وصول",
    NotificationType.BOOKING_CHECKOUT: "تسجيل مغادرة",
    NotificationType.UNIT_NEEDS_CLEANING: "وحدة تحتاج تنظيف",
    NotificationType.UNIT_NEEDS_MAINTENANCE: "وحدة تحتاج صيانة",
    NotificationType.UNIT_STATUS_CHANGED: "تغيير حالة وحدة",
    NotificationType.TASK_ASSIGNED: "مهمة جديدة",
    NotificationType.TASK_DUE: "مهمة مستحقة",
    NotificationType.TASK_COMPLETED: "مهمة مكتملة",
    NotificationType.CUSTOMER_VIP_ARRIVING: "عميل مميز قادم",
    NotificationType.CUSTOMER_BANNED: "حظر عميل",
    NotificationType.SYSTEM_ALERT: "تنبيه النظام",
    NotificationType.SYSTEM_UPDATE: "تحديث النظام",
}

# أيقونات الإشعارات
NOTIFICATION_ICONS = {
    NotificationType.BOOKING_NEW: "📅",
    NotificationType.BOOKING_CANCELLED: "❌",
    NotificationType.BOOKING_MODIFIED: "✏️",
    NotificationType.BOOKING_CHECKIN: "🏠",
    NotificationType.BOOKING_CHECKOUT: "👋",
    NotificationType.UNIT_NEEDS_CLEANING: "🧹",
    NotificationType.UNIT_NEEDS_MAINTENANCE: "🔧",
    NotificationType.UNIT_STATUS_CHANGED: "🔄",
    NotificationType.TASK_ASSIGNED: "📋",
    NotificationType.TASK_DUE: "⏰",
    NotificationType.TASK_COMPLETED: "✅",
    NotificationType.CUSTOMER_VIP_ARRIVING: "⭐",
    NotificationType.CUSTOMER_BANNED: "🚫",
    NotificationType.SYSTEM_ALERT: "⚠️",
    NotificationType.SYSTEM_UPDATE: "🔔",
}


class Notification(Base):
    """جدول الإشعارات"""
    __tablename__ = "notifications"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # المستخدم المستهدف (null = broadcast لجميع المستخدمين)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # نوع الإشعار
    type = Column(String(50), nullable=False, index=True)
    
    # محتوى الإشعار
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    
    # الكيان المرتبط (اختياري)
    entity_type = Column(String(50), nullable=True)  # booking, unit, customer, task, etc.
    entity_id = Column(String(36), nullable=True)
    
    # حالة القراءة
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    
    # التاريخ
    created_at = Column(DateTime, server_default=func.now(), index=True)
    
    # العلاقات
    user = relationship("User", foreign_keys=[user_id])
    
    def __repr__(self):
        return f"<Notification {self.type} - {self.title}>"
    
    @property
    def icon(self) -> str:
        """أيقونة الإشعار"""
        try:
            return NOTIFICATION_ICONS.get(NotificationType(self.type), "🔔")
        except:
            return "🔔"
    
    @property
    def type_label(self) -> str:
        """تسمية نوع الإشعار بالعربية"""
        try:
            return NOTIFICATION_TYPE_LABELS.get(NotificationType(self.type), self.type)
        except:
            return self.type

    def mark_as_read(self):
        """تحديد الإشعار كمقروء"""
        self.is_read = True
        self.read_at = datetime.utcnow()
