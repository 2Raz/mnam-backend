from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, desc
from typing import List, Optional

from ..database import get_db
from ..models.customer import Customer
from ..models.booking import Booking
from ..schemas.customer import (
    CustomerResponse, CustomerCreate, CustomerUpdate, 
    CustomerBanUpdate, CustomerWithBookings, CustomerStatsResponse
)
from ..utils.dependencies import get_current_user
from ..models.user import User
from ..services.employee_performance_service import log_customer_created, EmployeePerformanceService
from ..models.employee_performance import ActivityType
from ..services.customer_service import (
    normalize_phone, sanitize_name, get_customers_stats,
    get_incomplete_profile_customers
)
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/customers", tags=["العملاء"])


@router.get("/stats")
@router.get("/stats/", response_model=CustomerStatsResponse)
async def get_customer_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    إحصائيات العملاء:
    - إجمالي العملاء
    - العملاء الجدد (أقل من أسبوعين)
    - العملاء المميزين (زيارتين+)
    - البيانات المكتملة/الناقصة
    """
    from datetime import datetime, timedelta
    
    two_weeks_ago = datetime.utcnow() - timedelta(weeks=2)
    
    total = db.query(func.count(Customer.id)).scalar() or 0
    new_customers = db.query(func.count(Customer.id)).filter(
        Customer.created_at > two_weeks_ago
    ).scalar() or 0
    old_customers = total - new_customers
    
    vip_customers = db.query(func.count(Customer.id)).filter(
        Customer.completed_booking_count >= 2
    ).scalar() or 0
    regular_customers = total - vip_customers
    
    complete_profiles = db.query(func.count(Customer.id)).filter(
        Customer.is_profile_complete == True
    ).scalar() or 0
    incomplete_profiles = total - complete_profiles
    
    total_revenue = db.query(func.sum(Customer.total_revenue)).scalar() or 0.0
    
    return CustomerStatsResponse(
        total_customers=total,
        new_customers=new_customers,
        old_customers=old_customers,
        vip_customers=vip_customers,
        regular_customers=regular_customers,
        complete_profiles=complete_profiles,
        incomplete_profiles=incomplete_profiles,
        total_revenue=total_revenue
    )


@router.get("/incomplete")
@router.get("/incomplete/", response_model=List[CustomerResponse])
async def get_incomplete_customers(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    جلب العملاء اللي بياناتهم ناقصة (تم إنشاؤهم من الحجوزات)
    مفيد لعرض banner في لوحة التحكم
    """
    return get_incomplete_profile_customers(db, limit)


@router.get("")
@router.get("/", response_model=List[CustomerResponse])
async def get_all_customers(
    sort_incomplete_first: bool = Query(True, description="عرض العملاء الناقصة بياناتهم أولاً"),
    include_deleted: bool = Query(False, description="تضمين المحذوفين"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    الحصول على قائمة جميع العملاء
    - افتراضياً: العملاء الناقصة بياناتهم في الأعلى
    """
    query = db.query(Customer)
    
    if not include_deleted:
        query = query.filter(Customer.is_deleted == False)
    
    if sort_incomplete_first:
        # الناقصة أولاً، ثم حسب تاريخ الإنشاء
        customers = query.order_by(
            case((Customer.is_profile_complete == False, 0), else_=1),
            desc(Customer.created_at)
        ).all()
    else:
        customers = query.order_by(Customer.created_at.desc()).all()
    return customers


@router.get("/{customer_id}")
@router.get("/{customer_id}/", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على عميل محدد"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    return customer


@router.get("/phone/{phone}")
@router.get("/phone/{phone}/", response_model=CustomerResponse)
async def get_customer_by_phone(
    phone: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """البحث عن عميل برقم الجوال"""
    customer = db.query(Customer).filter(Customer.phone == phone).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    return customer


@router.post("")
@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    customer_data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """إنشاء عميل جديد"""
    # التحقق من عدم وجود عميل بنفس رقم الجوال
    normalized_phone = normalize_phone(customer_data.phone)
    existing = db.query(Customer).filter(Customer.phone == normalized_phone).first()
    if existing:
        raise HTTPException(
            status_code=400, 
            detail="يوجد عميل مسجل بهذا الرقم مسبقاً"
        )
    
    # تنظيف الاسم
    clean_name = sanitize_name(customer_data.name)
    if not clean_name or len(clean_name) < 2:
        raise HTTPException(
            status_code=400,
            detail="اسم العميل مطلوب (حرفين على الأقل)"
        )
    
    customer = Customer(
        name=clean_name,
        phone=normalized_phone,
        email=customer_data.email,
        gender=customer_data.gender,
        notes=customer_data.notes
    )
    
    # حساب حالة اكتمال البيانات (name+phone فقط)
    customer.update_profile_complete_status()
    
    db.add(customer)
    db.commit()
    db.refresh(customer)
    
    # تسجيل نشاط إضافة عميل
    log_customer_created(db, current_user.id, customer.id)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.CUSTOMER,
        entity_id=customer.id,
        entity_name=customer.name,
        description=f"إضافة عميل جديد: {customer.name}",
        new_values={
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email
        }
    )
    
    return customer


@router.put("/{customer_id}")
@router.put("/{customer_id}/", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    customer_data: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديث بيانات عميل"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    
    # التحقق من عدم تكرار رقم الجوال
    if customer_data.phone and customer_data.phone != customer.phone:
        existing = db.query(Customer).filter(
            Customer.phone == customer_data.phone,
            Customer.id != customer_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="رقم الجوال مستخدم لعميل آخر")
    
    update_data = customer_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(customer, field, value)
    
    # إعادة حساب حالة اكتمال البيانات بعد التحديث
    customer.update_profile_complete_status()
    
    db.commit()
    db.refresh(customer)
    
    # تسجيل نشاط تعديل عميل
    service = EmployeePerformanceService(db)
    service.log_activity(
        employee_id=current_user.id,
        activity_type=ActivityType.CUSTOMER_UPDATED,
        entity_type="customer",
        entity_id=customer.id,
        description=f"تعديل بيانات عميل: {customer.name}"
    )
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.CUSTOMER,
        entity_id=customer.id,
        entity_name=customer.name,
        description=f"تحديث بيانات عميل: {customer.name}",
        new_values=update_data
    )
    
    return customer


@router.patch("/{customer_id}/ban")
@router.patch("/{customer_id}/ban/", response_model=CustomerResponse)
async def ban_customer(
    customer_id: str,
    ban_data: CustomerBanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """حظر أو إلغاء حظر عميل"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    
    was_banned = customer.is_banned
    customer.is_banned = ban_data.is_banned
    customer.ban_reason = ban_data.ban_reason if ban_data.is_banned else None
    
    db.commit()
    db.refresh(customer)
    
    # تسجيل نشاط الحظر/إلغاء الحظر
    service = EmployeePerformanceService(db)
    if ban_data.is_banned and not was_banned:
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.CUSTOMER_BANNED,
            entity_type="customer",
            entity_id=customer.id,
            description=f"حظر عميل: {customer.name}"
        )
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.USER_BAN,
            entity_type=AuditEntityType.CUSTOMER,
            entity_id=customer.id,
            entity_name=customer.name,
            description=f"حظر عميل: {customer.name}",
            new_values={"is_banned": True, "ban_reason": ban_data.ban_reason}
        )
    elif not ban_data.is_banned and was_banned:
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.CUSTOMER_UNBANNED,
            entity_type="customer",
            entity_id=customer.id,
            description=f"إلغاء حظر عميل: {customer.name}"
        )
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.USER_UNBAN,
            entity_type=AuditEntityType.CUSTOMER,
            entity_id=customer.id,
            entity_name=customer.name,
            description=f"إلغاء حظر عميل: {customer.name}",
            new_values={"is_banned": False}
        )
    
    return customer


@router.get("/{customer_id}/bookings")
@router.get("/{customer_id}/bookings/")
async def get_customer_bookings(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على حجوزات عميل محدد"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    
    bookings = db.query(Booking).filter(Booking.customer_id == customer_id).order_by(Booking.check_in_date.desc()).all()
    
    return {
        "customer": customer,
        "bookings": bookings,
        "total_bookings": len(bookings)
    }


@router.delete("/{customer_id}")
@router.delete("/{customer_id}/")
async def delete_customer(
    customer_id: str,
    permanent: bool = Query(False, description="حذف نهائي"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    حذف عميل
    - permanent=false (افتراضي): Soft Delete
    - permanent=true: حذف نهائي (للمدير فقط)
    """
    from datetime import datetime
    
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    
    if permanent:
        if current_user.role not in ['admin', 'system_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحذف النهائي متاح للمدير فقط"
            )
        # حفظ اسم العميل قبل الحذف
        customer_name = customer.name
        customer_id_temp = customer.id
        
        # تسجيل في سجل الأنشطة قبل الحذف
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.PERMANENT_DELETE,
            entity_type=AuditEntityType.CUSTOMER,
            entity_id=customer_id_temp,
            entity_name=customer_name,
            description=f"حذف نهائي لعميل: {customer_name}"
        )
        db.delete(customer)
        db.commit()
        return {"message": "تم حذف العميل نهائياً"}
    else:
        customer.is_deleted = True
        customer.deleted_at = datetime.utcnow()
        customer.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.CUSTOMER,
            entity_id=customer.id,
            entity_name=customer.name,
            description=f"حذف عميل: {customer.name}"
        )
        return {"message": "تم حذف العميل بنجاح"}


@router.patch("/{customer_id}/restore")
@router.patch("/{customer_id}/restore/")
async def restore_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """استعادة عميل محذوف"""
    customer = db.query(Customer).filter(
        Customer.id == customer_id, 
        Customer.is_deleted == True
    ).first()
    if not customer:
        raise HTTPException(
            status_code=404, 
            detail="العميل غير موجود أو غير محذوف"
        )
    
    customer.is_deleted = False
    customer.deleted_at = None
    customer.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.CUSTOMER,
        entity_id=customer.id,
        entity_name=customer.name,
        description=f"استعادة عميل: {customer.name}"
    )
    
    return {"message": "تم استعادة العميل بنجاح"}


def get_or_create_customer(db: Session, name: str, phone: str) -> Customer:
    """
    دالة مساعدة: البحث عن عميل برقم الجوال أو إنشائه إذا لم يكن موجوداً
    وتحديث عدد الحجوزات
    """
    customer = db.query(Customer).filter(Customer.phone == phone).first()
    
    if customer:
        # تحديث الاسم إذا تغير
        if customer.name != name:
            customer.name = name
        # زيادة عدد الحجوزات
        customer.booking_count += 1
        db.commit()
        db.refresh(customer)
    else:
        # إنشاء عميل جديد
        customer = Customer(
            name=name,
            phone=phone,
            booking_count=1
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
    
    return customer
