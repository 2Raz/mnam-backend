import uuid
from datetime import datetime, timedelta
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, Float, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
import enum
from ..database import Base


class GenderEnum(str, enum.Enum):
    """أنواع الجنس"""
    MALE = "male"  # ذكر
    FEMALE = "female"  # أنثى


class Customer(Base):
    """جدول العملاء - يحتوي على بيانات الضيوف المتكررين"""
    __tablename__ = "customers"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # بيانات العميل الأساسية
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, unique=True, index=True)  # رقم الجوال كدليل فريد
    email = Column(String(255), nullable=True)  # البريد الإلكتروني (اختياري)
    gender = Column(SQLEnum(GenderEnum), nullable=True)  # الجنس (اختياري)
    
    # إحصائيات
    booking_count = Column(Integer, default=0)  # عدد مرات الحجز
    completed_booking_count = Column(Integer, default=0)  # عدد الحجوزات المكتملة
    total_revenue = Column(Float, default=0.0)  # إجمالي الإيراد من العميل
    
    # حالة العميل
    is_banned = Column(Boolean, default=False)  # هل العميل محظور؟
    ban_reason = Column(Text, nullable=True)  # سبب الحظر (اختياري)
    is_profile_complete = Column(Boolean, default=False)  # هل بيانات العميل مكتملة؟
    
    # ملاحظات
    notes = Column(Text, nullable=True)
    
    # التواريخ
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Soft Delete
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # العلاقات
    bookings = relationship("Booking", back_populates="customer")
    
    @hybrid_property
    def visitor_type(self) -> str:
        """
        نوع الزائر:
        - مميز: زيارتين أو أكثر
        - عادي: زيارة واحدة فقط
        """
        if self.completed_booking_count >= 2:
            return "مميز"
        return "عادي"
    
    @hybrid_property
    def customer_status(self) -> str:
        """
        حالة العميل (جديد أو قديم):
        - new: لم يمر أسبوعين على إضافته
        - old: مر أسبوعين أو أكثر على إضافته
        """
        if self.created_at:
            two_weeks_ago = datetime.utcnow() - timedelta(weeks=2)
            if self.created_at > two_weeks_ago:
                return "new"
        return "old"
    
    def check_profile_complete(self) -> bool:
        """
        التحقق من اكتمال بيانات العميل
        البيانات المطلوبة: الاسم، الهاتف فقط
        (email, gender, notes اختيارية ولا تؤثر على حالة الاكتمال)
        """
        return all([
            self.name and len(self.name.strip()) >= 2,
            self.phone and len(self.phone.strip()) >= 9
        ])
    
    def update_profile_complete_status(self):
        """تحديث حالة اكتمال البيانات"""
        self.is_profile_complete = self.check_profile_complete()
    
    def __repr__(self):
        return f"<Customer {self.name} - {self.phone}>"
