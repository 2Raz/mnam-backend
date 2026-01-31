"""
نموذج سجل الأنشطة - Audit Log Model
يسجل جميع العمليات المهمة في النظام
"""
from sqlalchemy import Column, String, DateTime, Text, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
from decimal import Decimal
import uuid
import enum

from ..database import Base


def _serialize_for_json(obj):
    """Convert non-JSON-serializable types to serializable ones"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_json(i) for i in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, enum.Enum):
        return obj.value
    return obj


class ActivityType(str, enum.Enum):
    """أنواع الأنشطة"""
    # CRUD Operations
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"
    
    # Auth
    LOGIN = "login"
    LOGOUT = "logout"
    PASSWORD_CHANGE = "password_change"
    
    # Business
    BOOKING_CONFIRM = "booking_confirm"
    BOOKING_CANCEL = "booking_cancel"
    BOOKING_CHECKIN = "booking_checkin"
    BOOKING_CHECKOUT = "booking_checkout"
    
    # Admin
    USER_BAN = "user_ban"
    USER_UNBAN = "user_unban"
    ROLE_CHANGE = "role_change"
    
    # System
    SYNC = "sync"
    IMPORT = "import"
    EXPORT = "export"


class EntityType(str, enum.Enum):
    """أنواع الكيانات"""
    USER = "user"
    OWNER = "owner"
    PROJECT = "project"
    UNIT = "unit"
    BOOKING = "booking"
    CUSTOMER = "customer"
    TASK = "task"
    TRANSACTION = "transaction"
    CHANNEL = "channel"
    SYSTEM = "system"


ACTIVITY_LABELS = {
    ActivityType.CREATE: "إنشاء",
    ActivityType.UPDATE: "تحديث",
    ActivityType.DELETE: "حذف",
    ActivityType.RESTORE: "استعادة",
    ActivityType.PERMANENT_DELETE: "حذف نهائي",
    ActivityType.LOGIN: "تسجيل دخول",
    ActivityType.LOGOUT: "تسجيل خروج",
    ActivityType.PASSWORD_CHANGE: "تغيير كلمة المرور",
    ActivityType.BOOKING_CONFIRM: "تأكيد حجز",
    ActivityType.BOOKING_CANCEL: "إلغاء حجز",
    ActivityType.BOOKING_CHECKIN: "تسجيل وصول",
    ActivityType.BOOKING_CHECKOUT: "تسجيل مغادرة",
    ActivityType.USER_BAN: "حظر مستخدم",
    ActivityType.USER_UNBAN: "إلغاء حظر",
    ActivityType.ROLE_CHANGE: "تغيير صلاحية",
    ActivityType.SYNC: "مزامنة",
    ActivityType.IMPORT: "استيراد",
    ActivityType.EXPORT: "تصدير",
}

ENTITY_LABELS = {
    EntityType.USER: "مستخدم",
    EntityType.OWNER: "مالك",
    EntityType.PROJECT: "مشروع",
    EntityType.UNIT: "وحدة",
    EntityType.BOOKING: "حجز",
    EntityType.CUSTOMER: "عميل",
    EntityType.TASK: "مهمة",
    EntityType.TRANSACTION: "معاملة",
    EntityType.CHANNEL: "قناة",
    EntityType.SYSTEM: "النظام",
}


class AuditLog(Base):
    """
    سجل الأنشطة - يحتفظ بكل العمليات المهمة
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # من قام بالعملية
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name = Column(String(100), nullable=True)  # نحتفظ بالاسم حتى لو حُذف المستخدم
    
    # نوع العملية
    activity_type = Column(SQLEnum(ActivityType), nullable=False, index=True)
    
    # الكيان المتأثر
    entity_type = Column(SQLEnum(EntityType), nullable=False, index=True)
    entity_id = Column(String(36), nullable=True, index=True)
    entity_name = Column(String(200), nullable=True)  # اسم الكيان للعرض
    
    # تفاصيل إضافية
    description = Column(Text, nullable=True)  # وصف العملية
    old_values = Column(JSON, nullable=True)  # القيم القديمة (للتحديث/الحذف)
    new_values = Column(JSON, nullable=True)  # القيم الجديدة (للإنشاء/التحديث)
    
    # معلومات تقنية
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # التوقيت
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationship
    user = relationship("User", backref="audit_logs", foreign_keys=[user_id])
    
    def __repr__(self):
        return f"<AuditLog {self.activity_type.value} {self.entity_type.value} by {self.user_name}>"
    
    @classmethod
    def log(cls, db, user, activity_type: ActivityType, entity_type: EntityType,
            entity_id: str = None, entity_name: str = None, description: str = None,
            old_values: dict = None, new_values: dict = None,
            ip_address: str = None, user_agent: str = None):
        """
        تسجيل نشاط جديد
        """
        # Serialize values to handle Decimal and other non-JSON types
        serialized_old = _serialize_for_json(old_values)
        serialized_new = _serialize_for_json(new_values)
        
        log_entry = cls(
            user_id=user.id if user else None,
            user_name=f"{user.first_name} {user.last_name}" if user else "النظام",
            activity_type=activity_type,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            description=description,
            old_values=serialized_old,
            new_values=serialized_new,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log_entry)
        db.commit()
        return log_entry

