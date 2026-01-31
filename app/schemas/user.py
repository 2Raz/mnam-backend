from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    """أدوار المستخدمين - يجب أن تتطابق مع models/user.py"""
    SYSTEM_OWNER = "system_owner"
    ADMIN = "admin"
    OWNERS_AGENT = "owners_agent"
    CUSTOMERS_AGENT = "customers_agent"


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="اسم المستخدم")
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100, description="الاسم الأول")
    last_name: str = Field(..., min_length=1, max_length=100, description="اسم العائلة")
    phone: Optional[str] = Field(None, max_length=20, description="رقم الهاتف")
    role: UserRole = UserRole.CUSTOMERS_AGENT


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128, description="كلمة المرور")


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: str
    is_active: bool
    is_system_owner: bool = False
    last_login: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserInDB(UserResponse):
    hashed_password: str


class AssignableRoleResponse(BaseModel):
    """الأدوار المتاحة للتعيين"""
    value: str
    label: str


# ======== إعدادات الحساب ========

class ChangePasswordRequest(BaseModel):
    """طلب تغيير كلمة المرور"""
    current_password: str
    new_password: str


class UpdateMyProfileRequest(BaseModel):
    """طلب تحديث الملف الشخصي"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class MyProfileResponse(BaseModel):
    """الملف الشخصي الكامل"""
    id: str
    username: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    role: str
    role_label: str
    is_active: bool
    is_system_owner: bool = False
    last_login: Optional[datetime] = None
    created_at: datetime
    
    # إحصائيات سريعة
    today_activities: int = 0
    today_duration_minutes: int = 0
    pending_tasks_count: int = 0
    
    class Config:
        from_attributes = True

