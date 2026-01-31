"""
خدمة تسجيل الأنشطة - Audit Logging Service
توفر دوال مساعدة لتسجيل العمليات في سجل الأنشطة
"""
from sqlalchemy.orm import Session
from fastapi import Request
from typing import Optional, Any, Dict

from ..models.audit_log import AuditLog, ActivityType, EntityType
from ..models.user import User


def get_client_ip(request: Request) -> Optional[str]:
    """الحصول على IP العميل"""
    # Check for forwarded IP (behind proxy)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    # Check for real IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct client IP
    if request.client:
        return request.client.host
    return None


def get_user_agent(request: Request) -> Optional[str]:
    """الحصول على User-Agent"""
    return request.headers.get("User-Agent")


def log_activity(
    db: Session,
    user: Optional[User],
    activity_type: ActivityType,
    entity_type: EntityType,
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    description: Optional[str] = None,
    old_values: Optional[Dict[str, Any]] = None,
    new_values: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """
    تسجيل نشاط في سجل الأنشطة
    
    Args:
        db: جلسة قاعدة البيانات
        user: المستخدم الذي قام بالعملية (None للنظام)
        activity_type: نوع النشاط (create, update, delete, etc.)
        entity_type: نوع الكيان (owner, project, unit, etc.)
        entity_id: معرف الكيان
        entity_name: اسم الكيان للعرض
        description: وصف إضافي للعملية
        old_values: القيم القديمة (للتحديث/الحذف)
        new_values: القيم الجديدة (للإنشاء/التحديث)
        request: كائن الطلب للحصول على IP و User-Agent
    """
    ip_address = get_client_ip(request) if request else None
    user_agent = get_user_agent(request) if request else None
    
    log_entry = AuditLog(
        user_id=user.id if user else None,
        user_name=f"{user.first_name} {user.last_name}" if user else "النظام",
        activity_type=activity_type,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=description,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        user_agent=user_agent[:500] if user_agent and len(user_agent) > 500 else user_agent,
    )
    db.add(log_entry)
    db.commit()
    return log_entry


def log_create(
    db: Session,
    user: User,
    entity_type: EntityType,
    entity_id: str,
    entity_name: str,
    new_values: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية إنشاء"""
    return log_activity(
        db=db,
        user=user,
        activity_type=ActivityType.CREATE,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=f"تم إنشاء {entity_name}",
        new_values=new_values,
        request=request
    )


def log_update(
    db: Session,
    user: User,
    entity_type: EntityType,
    entity_id: str,
    entity_name: str,
    old_values: Optional[Dict[str, Any]] = None,
    new_values: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية تحديث"""
    # حساب التغييرات
    changes = []
    if old_values and new_values:
        for key, new_val in new_values.items():
            old_val = old_values.get(key)
            if old_val != new_val:
                changes.append(key)
    
    description = f"تم تحديث {entity_name}"
    if changes:
        description += f" (الحقول: {', '.join(changes[:5])})"
        if len(changes) > 5:
            description += f" و{len(changes) - 5} حقول أخرى"
    
    return log_activity(
        db=db,
        user=user,
        activity_type=ActivityType.UPDATE,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=description,
        old_values=old_values,
        new_values=new_values,
        request=request
    )


def log_delete(
    db: Session,
    user: User,
    entity_type: EntityType,
    entity_id: str,
    entity_name: str,
    permanent: bool = False,
    old_values: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية حذف"""
    activity = ActivityType.PERMANENT_DELETE if permanent else ActivityType.DELETE
    description = f"تم {'الحذف النهائي' if permanent else 'حذف'} {entity_name}"
    
    return log_activity(
        db=db,
        user=user,
        activity_type=activity,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=description,
        old_values=old_values,
        request=request
    )


def log_restore(
    db: Session,
    user: User,
    entity_type: EntityType,
    entity_id: str,
    entity_name: str,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية استعادة"""
    return log_activity(
        db=db,
        user=user,
        activity_type=ActivityType.RESTORE,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        description=f"تم استعادة {entity_name}",
        request=request
    )


def log_login(
    db: Session,
    user: User,
    request: Optional[Request] = None,
    success: bool = True
) -> AuditLog:
    """تسجيل عملية تسجيل دخول"""
    return log_activity(
        db=db,
        user=user,
        activity_type=ActivityType.LOGIN,
        entity_type=EntityType.USER,
        entity_id=user.id,
        entity_name=f"{user.first_name} {user.last_name}",
        description=f"تسجيل دخول {'ناجح' if success else 'فاشل'}",
        request=request
    )


def log_logout(
    db: Session,
    user: User,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية تسجيل خروج"""
    return log_activity(
        db=db,
        user=user,
        activity_type=ActivityType.LOGOUT,
        entity_type=EntityType.USER,
        entity_id=user.id,
        entity_name=f"{user.first_name} {user.last_name}",
        description="تسجيل خروج",
        request=request
    )


def log_booking_action(
    db: Session,
    user: User,
    activity_type: ActivityType,
    booking_id: str,
    guest_name: str,
    unit_name: str = "",
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية متعلقة بحجز"""
    action_names = {
        ActivityType.BOOKING_CONFIRM: "تأكيد",
        ActivityType.BOOKING_CANCEL: "إلغاء",
        ActivityType.BOOKING_CHECKIN: "تسجيل وصول",
        ActivityType.BOOKING_CHECKOUT: "تسجيل مغادرة",
    }
    
    action_name = action_names.get(activity_type, "عملية")
    description = f"{action_name} حجز {guest_name}"
    if unit_name:
        description += f" في {unit_name}"
    
    return log_activity(
        db=db,
        user=user,
        activity_type=activity_type,
        entity_type=EntityType.BOOKING,
        entity_id=booking_id,
        entity_name=guest_name,
        description=description,
        request=request
    )


def log_user_ban(
    db: Session,
    admin: User,
    target_user_id: str,
    target_user_name: str,
    is_ban: bool,
    reason: Optional[str] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """تسجيل عملية حظر/إلغاء حظر"""
    activity = ActivityType.USER_BAN if is_ban else ActivityType.USER_UNBAN
    description = f"{'حظر' if is_ban else 'إلغاء حظر'} المستخدم {target_user_name}"
    if reason:
        description += f" - السبب: {reason}"
    
    return log_activity(
        db=db,
        user=admin,
        activity_type=activity,
        entity_type=EntityType.USER,
        entity_id=target_user_id,
        entity_name=target_user_name,
        description=description,
        request=request
    )


def model_to_dict(obj, exclude: list = None) -> Dict[str, Any]:
    """تحويل model إلى dictionary للتسجيل"""
    exclude = exclude or ['_sa_instance_state', 'hashed_password']
    result = {}
    
    for column in obj.__table__.columns:
        key = column.name
        if key not in exclude:
            value = getattr(obj, key, None)
            # تحويل التواريخ إلى نص
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            # تحويل Enum إلى قيمة
            if hasattr(value, 'value'):
                value = value.value
            result[key] = value
    
    return result
