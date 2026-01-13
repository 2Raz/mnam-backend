import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

from ..database import Base


class UserRole(str, enum.Enum):
    """أدوار المستخدمين في النظام"""
    SYSTEM_OWNER = "system_owner"     # مالك النظام - كل الصلاحيات + إدارة جميع الرتب
    ADMIN = "admin"                    # مدير النظام - كل شي ما عدا التعديل على Admin+
    OWNERS_AGENT = "owners_agent"      # وكيل الملاك - الرئيسية، الملاك، الوحدات، المشاريع
    CUSTOMERS_AGENT = "customers_agent" # وكيل العملاء - الوحدات (عرض) + الحجوزات (تعديل)


# تسميات الأدوار بالعربية
ROLE_LABELS = {
    UserRole.SYSTEM_OWNER: "مالك النظام",
    UserRole.ADMIN: "مدير نظام",
    UserRole.OWNERS_AGENT: "وكيل ملاك",
    UserRole.CUSTOMERS_AGENT: "وكيل عملاء",
}

# ترتيب الأدوار من الأعلى للأدنى (للمقارنة)
ROLE_HIERARCHY = {
    UserRole.SYSTEM_OWNER: 4,
    UserRole.ADMIN: 3,
    UserRole.OWNERS_AGENT: 2,
    UserRole.CUSTOMERS_AGENT: 1,
}

# الأدوار المتاحة للاختيار حسب رتبة المستخدم الحالي
def get_assignable_roles(current_user_role: str) -> list:
    """الحصول على الأدوار التي يمكن للمستخدم الحالي تعيينها"""
    current_level = ROLE_HIERARCHY.get(UserRole(current_user_role), 0)
    
    if current_level == 4:  # System Owner
        # يمكنه تعيين كل الأدوار ما عدا System Owner
        return [UserRole.ADMIN, UserRole.OWNERS_AGENT, UserRole.CUSTOMERS_AGENT]
    elif current_level == 3:  # Admin
        # يمكنه تعيين Owners_Agent و Customers_Agent فقط
        return [UserRole.OWNERS_AGENT, UserRole.CUSTOMERS_AGENT]
    else:
        return []


# الأدوار المتاحة للتعيين (بدون System_Owner) - للـ API
ASSIGNABLE_ROLES = [UserRole.ADMIN, UserRole.OWNERS_AGENT, UserRole.CUSTOMERS_AGENT]


class User(Base):
    """نموذج المستخدم في النظام"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), default="")
    phone = Column(String(20), nullable=True)
    
    role = Column(String(20), default=UserRole.CUSTOMERS_AGENT.value)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime, nullable=True)
    
    # معرف خاص لمالك النظام - لا يمكن تغييره
    is_system_owner = Column(Boolean, default=False)
    
    # Relationship to refresh tokens
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(username='{self.username}', role='{self.role}')>"
    
    @property
    def role_level(self) -> int:
        """مستوى صلاحيات المستخدم"""
        try:
            return ROLE_HIERARCHY.get(UserRole(self.role), 0)
        except:
            return 0
    
    @property
    def is_admin_or_higher(self) -> bool:
        """هل المستخدم مدير أو أعلى؟"""
        return self.role_level >= 3
    
    @property
    def is_owners_agent_or_higher(self) -> bool:
        """هل المستخدم وكيل ملاك أو أعلى؟"""
        return self.role_level >= 2
    
    @property
    def is_customers_agent_or_higher(self) -> bool:
        """هل المستخدم وكيل عملاء أو أعلى؟"""
        return self.role_level >= 1
    
    @property
    def has_full_access(self) -> bool:
        """هل المستخدم لديه صلاحيات كاملة؟ (مالك النظام فقط)"""
        return self.role == UserRole.SYSTEM_OWNER.value and self.is_system_owner
    
    @property
    def can_be_deleted(self) -> bool:
        """هل يمكن حذف هذا المستخدم؟"""
        return not self.is_system_owner
    
    def can_modify_user(self, target_user: 'User') -> bool:
        """هل يمكن لهذا المستخدم تعديل مستخدم آخر؟"""
        if target_user.is_system_owner:
            return False  # لا أحد يعدل على System Owner
        if self.is_system_owner:
            return True  # System Owner يعدل على الكل
        if self.role == UserRole.ADMIN.value and target_user.role == UserRole.ADMIN.value:
            return False  # Admin لا يعدل على Admin آخر
        return self.role_level > target_user.role_level


# بيانات مالك النظام الافتراضي
SYSTEM_OWNER_DATA = {
    "username": "Head_Admin",
    "email": "rzogi20@gmail.com",
    "password": "H112as112!",
    "first_name": "Owner",
    "last_name": ".",
    "role": UserRole.SYSTEM_OWNER.value,
    "is_system_owner": True,
    "is_active": True,
}
