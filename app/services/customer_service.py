"""
Customer Service - Auto Customer Sync from Bookings
====================================================
This service handles:
1. Phone number normalization (Saudi format)
2. Name sanitization
3. Customer upsert logic (create or update by phone)
"""

import re
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from ..models.customer import Customer, GenderEnum


def normalize_phone(phone: str) -> str:
    """
    تنظيف وتوحيد صيغة رقم الجوال السعودي
    
    Supported formats:
    - +966501234567 -> 0501234567
    - 966501234567 -> 0501234567
    - 00966501234567 -> 0501234567
    - 0501234567 -> 0501234567
    - 501234567 -> 0501234567
    - 05 01 23 45 67 -> 0501234567
    
    Returns normalized phone in format: 05xxxxxxxx
    """
    if not phone:
        return ""
    
    # إزالة كل شيء عدا الأرقام
    digits_only = re.sub(r'\D', '', phone)
    
    if not digits_only:
        return ""
    
    # إزالة رمز الدولة إذا موجود
    # +966 or 966 or 00966
    if digits_only.startswith('966') and len(digits_only) >= 12:
        digits_only = digits_only[3:]
    elif digits_only.startswith('00966') and len(digits_only) >= 14:
        digits_only = digits_only[5:]
    
    # إضافة صفر في البداية إذا يبدأ بـ 5
    if digits_only.startswith('5') and len(digits_only) == 9:
        digits_only = '0' + digits_only
    
    # التحقق من الصيغة النهائية (يجب أن يكون 10 أرقام يبدأ بـ 05)
    if len(digits_only) == 10 and digits_only.startswith('05'):
        return digits_only
    
    # إذا الرقم ما ينطبق على الصيغة السعودية، رجّعه كما هو (منظف)
    return digits_only


def sanitize_name(name: str) -> str:
    """
    تنظيف اسم العميل:
    - إزالة المسافات الزائدة
    - trim
    - إزالة الأحرف الغير مرغوبة
    """
    if not name:
        return ""
    
    # إزالة الأحرف الخاصة (ماعدا العربية والإنجليزية والمسافات)
    cleaned = re.sub(r'[^\w\s\u0600-\u06FF]', '', name)
    
    # تنظيف المسافات الزائدة
    cleaned = ' '.join(cleaned.split())
    
    return cleaned.strip()


def validate_customer_info(name: str, phone: str) -> Tuple[bool, str]:
    """
    التحقق من صحة بيانات العميل الأساسية
    
    Returns: (is_valid, error_message)
    """
    if not name or len(name.strip()) < 2:
        return False, "اسم العميل مطلوب (حرفين على الأقل)"
    
    if not phone or len(phone.strip()) < 9:
        return False, "رقم الجوال مطلوب"
    
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return False, "رقم الجوال غير صالح"
    
    return True, ""


def upsert_customer_from_booking(
    db: Session,
    name: str,
    phone: str,
    gender: Optional[str] = None,
    booking_amount: float = 0.0,
    is_new_booking: bool = True
) -> Tuple[Customer, bool]:
    """
    إنشاء أو تحديث عميل من بيانات الحجز
    
    Args:
        db: Database session
        name: اسم العميل (سيتم تنظيفه)
        phone: رقم الجوال (سيتم توحيده)
        gender: جنس العميل (اختياري)
        booking_amount: مبلغ الحجز (لتحديث total_revenue)
        is_new_booking: هل هو حجز جديد (لزيادة booking_count)
    
    Returns:
        Tuple[Customer, bool]: (العميل، هل تم إنشاؤه جديداً)
    """
    # تنظيف البيانات
    clean_name = sanitize_name(name)
    normalized_phone = normalize_phone(phone)
    
    # تحويل gender إلى GenderEnum إذا موجود
    gender_enum = None
    if gender:
        gender_lower = gender.lower().strip()
        if gender_lower in ['male', 'ذكر', 'm']:
            gender_enum = GenderEnum.MALE
        elif gender_lower in ['female', 'أنثى', 'انثى', 'f']:
            gender_enum = GenderEnum.FEMALE
    
    # البحث عن العميل بالرقم
    customer = db.query(Customer).filter(
        Customer.phone == normalized_phone
    ).first()
    
    is_new_customer = False
    
    if customer:
        # ========== تحديث عميل موجود ==========
        # تحديث الحقول الناقصة فقط (لا نخرب البيانات الموجودة)
        
        # تحديث الاسم إذا الجديد أفضل (أطول)
        if clean_name and len(clean_name) > len(customer.name or ''):
            customer.name = clean_name
        
        # تحديث الجنس إذا ما كان موجود
        if gender_enum and not customer.gender:
            customer.gender = gender_enum
        
        # زيادة عدد الحجوزات
        if is_new_booking:
            customer.booking_count = (customer.booking_count or 0) + 1
            # إضافة مبلغ الحجز للإيراد الكلي
            customer.total_revenue = (customer.total_revenue or 0.0) + booking_amount
        
        # تحديث حالة اكتمال البيانات
        customer.update_profile_complete_status()
        
    else:
        # ========== إنشاء عميل جديد ==========
        is_new_customer = True
        
        customer = Customer(
            name=clean_name,
            phone=normalized_phone,
            gender=gender_enum,
            booking_count=1 if is_new_booking else 0,
            completed_booking_count=0,
            total_revenue=booking_amount if is_new_booking else 0.0,
            is_banned=False,
            is_profile_complete=False,  # ناقص لأنه من حجز
        )
        
        # التحقق من اكتمال البيانات
        customer.update_profile_complete_status()
        
        db.add(customer)
    
    db.flush()  # للحصول على ID
    db.refresh(customer)
    
    return customer, is_new_customer


def get_customer_by_phone(db: Session, phone: str) -> Optional[Customer]:
    """
    البحث عن عميل برقم الجوال (مع توحيد الصيغة)
    """
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    
    return db.query(Customer).filter(
        Customer.phone == normalized
    ).first()


def get_incomplete_profile_customers(db: Session, limit: int = 50):
    """
    جلب العملاء اللي بياناتهم ناقصة
    """
    return db.query(Customer).filter(
        Customer.is_profile_complete == False
    ).order_by(Customer.created_at.desc()).limit(limit).all()


def get_customers_stats(db: Session) -> dict:
    """
    إحصائيات العملاء
    """
    from sqlalchemy import func
    
    total = db.query(func.count(Customer.id)).scalar() or 0
    incomplete = db.query(func.count(Customer.id)).filter(
        Customer.is_profile_complete == False
    ).scalar() or 0
    complete = total - incomplete
    banned = db.query(func.count(Customer.id)).filter(
        Customer.is_banned == True
    ).scalar() or 0
    
    return {
        "total_customers": total,
        "complete_profiles": complete,
        "incomplete_profiles": incomplete,
        "banned_customers": banned,
    }
