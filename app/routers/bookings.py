from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import date, timedelta
from decimal import Decimal

from ..database import get_db
from ..models.booking import Booking, BookingStatus as BookingStatusEnum
from ..models.unit import Unit
from ..models.project import Project
from ..models.customer import Customer
from ..schemas.booking import (
    BookingResponse, BookingCreate, BookingUpdate, 
    BookingStatusUpdate, BookingAvailabilityCheck
)
from ..utils.dependencies import get_current_user
from ..models.user import User
from ..services.employee_performance_service import (
    EmployeePerformanceService,
    log_booking_created, log_booking_completed, log_booking_cancelled,
    log_customer_created
)
from ..models.employee_performance import ActivityType
from ..services.customer_service import (
    normalize_phone, sanitize_name, validate_customer_info,
    upsert_customer_from_booking
)

router = APIRouter(prefix="/api/bookings", tags=["الحجوزات"])


def check_booking_overlap(
    db: Session, 
    unit_id: str, 
    check_in: date, 
    check_out: date, 
    exclude_booking_id: Optional[str] = None
) -> bool:
    """التحقق من تداخل الحجوزات"""
    query = db.query(Booking).filter(
        Booking.unit_id == unit_id,
        Booking.status.in_(["مؤكد", "دخول"]),
        Booking.check_in_date < check_out,
        Booking.check_out_date > check_in
    )
    
    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)
    
    return query.first() is not None


def calculate_booking_price(unit: Unit, check_in: date, check_out: date) -> Decimal:
    """حساب سعر الحجز بناءً على أيام الأسبوع ونهاية الأسبوع"""
    total = Decimal("0")
    current = check_in
    
    while current < check_out:
        # الجمعة = 4, السبت = 5 (في Python weekday)
        is_weekend = current.weekday() in [4, 5]
        if is_weekend:
            total += Decimal(str(unit.price_in_weekends))
        else:
            total += Decimal(str(unit.price_days_of_week))
        current += timedelta(days=1)
    
    return total


@router.get("")
@router.get("/", response_model=List[BookingResponse])
async def get_all_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع الحجوزات"""
    bookings = db.query(Booking).order_by(Booking.check_in_date.desc()).all()
    
    result = []
    for booking in bookings:
        unit = booking.unit
        project = unit.project if unit else None
        
        result.append(BookingResponse(
            id=booking.id,
            unit_id=booking.unit_id,
            guest_name=booking.guest_name,
            guest_phone=booking.guest_phone,
            check_in_date=booking.check_in_date,
            check_out_date=booking.check_out_date,
            total_price=booking.total_price,
            status=booking.status,
            notes=booking.notes,
            project_id=project.id if project else "",
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else "غير معروف",
            created_at=booking.created_at,
            updated_at=booking.updated_at
        ))
    
    return result


@router.get("/monthly")
@router.get("/monthly/", response_model=List[BookingResponse])
async def get_monthly_bookings(
    year: int = Query(..., description="السنة"),
    month: int = Query(..., ge=1, le=12, description="الشهر (1-12)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على حجوزات شهر محدد"""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    bookings = db.query(Booking).filter(
        or_(
            and_(Booking.check_in_date >= start_date, Booking.check_in_date < end_date),
            and_(Booking.check_out_date > start_date, Booking.check_out_date <= end_date),
            and_(Booking.check_in_date < start_date, Booking.check_out_date > end_date)
        )
    ).order_by(Booking.check_in_date).all()
    
    result = []
    for booking in bookings:
        unit = booking.unit
        project = unit.project if unit else None
        
        result.append(BookingResponse(
            id=booking.id,
            unit_id=booking.unit_id,
            guest_name=booking.guest_name,
            guest_phone=booking.guest_phone,
            check_in_date=booking.check_in_date,
            check_out_date=booking.check_out_date,
            total_price=booking.total_price,
            status=booking.status,
            notes=booking.notes,
            project_id=project.id if project else "",
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else "غير معروف",
            created_at=booking.created_at,
            updated_at=booking.updated_at
        ))
    
    return result


@router.get("/check-availability")
@router.get("/check-availability/")
async def check_availability(
    unit_id: str,
    check_in_date: date,
    check_out_date: date,
    exclude_booking_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """التحقق من توفر الوحدة للحجز"""
    has_overlap = check_booking_overlap(db, unit_id, check_in_date, check_out_date, exclude_booking_id)
    
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    suggested_price = None
    if unit:
        suggested_price = calculate_booking_price(unit, check_in_date, check_out_date)
    
    return {
        "available": not has_overlap,
        "suggested_price": suggested_price,
        "message": "الوحدة متاحة للحجز" if not has_overlap else "يوجد تداخل مع حجز آخر"
    }


@router.get("/{booking_id}")
@router.get("/{booking_id}/", response_model=BookingResponse)
async def get_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات حجز محدد"""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    unit = booking.unit
    project = unit.project if unit else None
    
    return BookingResponse(
        id=booking.id,
        unit_id=booking.unit_id,
        guest_name=booking.guest_name,
        guest_phone=booking.guest_phone,
        check_in_date=booking.check_in_date,
        check_out_date=booking.check_out_date,
        total_price=booking.total_price,
        status=booking.status,
        notes=booking.notes,
        project_id=project.id if project else "",
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name if unit else "غير معروف",
        created_at=booking.created_at,
        updated_at=booking.updated_at
    )


@router.post("")
@router.post("/", response_model=BookingResponse)
async def create_booking(
    booking_data: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    إنشاء حجز جديد مع مزامنة تلقائية للعملاء (Auto Customer Sync)
    
    - يتم تنظيف وتوحيد رقم الجوال تلقائياً
    - يتم تنظيف اسم العميل
    - إذا العميل موجود: يتم تحديث بياناته الناقصة فقط
    - إذا العميل جديد: يتم إنشاؤه تلقائياً
    """
    # ========== التحقق من الوحدة ==========
    unit = db.query(Unit).filter(Unit.id == booking_data.unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الوحدة غير موجودة"
        )
    
    # ========== تنظيف بيانات العميل ==========
    clean_name = sanitize_name(booking_data.guest_name)
    normalized_phone = normalize_phone(booking_data.guest_phone or "")
    
    # ========== التحقق من صحة البيانات ==========
    if not clean_name or len(clean_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="اسم الضيف مطلوب (حرفين على الأقل)"
        )
    
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="رقم جوال الضيف مطلوب وغير صالح"
        )
    
    # ========== التحقق من تداخل الحجوزات ==========
    if check_booking_overlap(db, booking_data.unit_id, booking_data.check_in_date, booking_data.check_out_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يوجد تداخل مع حجز آخر في هذه الفترة"
        )
    
    # ========== Auto Customer Sync (Upsert) ==========
    booking_amount = float(booking_data.total_price)
    guest_gender = booking_data.guest_gender.value if booking_data.guest_gender else None
    
    customer, is_new_customer = upsert_customer_from_booking(
        db=db,
        name=clean_name,
        phone=normalized_phone,
        gender=guest_gender,
        booking_amount=booking_amount,
        is_new_booking=True
    )
    
    # التحقق من حظر العميل
    if customer.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"العميل محظور. السبب: {customer.ban_reason or 'غير محدد'}"
        )
    
    # ========== إنشاء الحجز ==========
    project = unit.project
    new_booking = Booking(
        unit_id=booking_data.unit_id,
        customer_id=customer.id,
        guest_name=clean_name,  # الاسم المنظف
        guest_phone=normalized_phone,  # الرقم الموحد
        check_in_date=booking_data.check_in_date,
        check_out_date=booking_data.check_out_date,
        total_price=booking_data.total_price,
        status=booking_data.status.value,
        notes=booking_data.notes,
        created_by_id=current_user.id
    )
    
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    # ========== تسجيل النشاطات ==========
    log_booking_created(db, current_user.id, new_booking.id, booking_amount)
    
    # تسجيل نشاط إضافة عميل جديد إذا تم إنشاؤه
    if is_new_customer:
        log_customer_created(db, current_user.id, customer.id)
    
    return BookingResponse(
        id=new_booking.id,
        unit_id=new_booking.unit_id,
        guest_name=new_booking.guest_name,
        guest_phone=new_booking.guest_phone,
        check_in_date=new_booking.check_in_date,
        check_out_date=new_booking.check_out_date,
        total_price=new_booking.total_price,
        status=new_booking.status,
        notes=new_booking.notes,
        project_id=project.id if project else "",
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name,
        customer_id=customer.id,
        customer_name=customer.name,
        customer_is_banned=customer.is_banned,
        created_at=new_booking.created_at,
        updated_at=new_booking.updated_at
    )


@router.put("/{booking_id}")
@router.put("/{booking_id}/", response_model=BookingResponse)
async def update_booking(
    booking_id: str,
    booking_data: BookingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديث بيانات حجز"""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    # Check for date overlap if dates are being updated
    update_data = booking_data.model_dump(exclude_unset=True)
    new_check_in = update_data.get("check_in_date", booking.check_in_date)
    new_check_out = update_data.get("check_out_date", booking.check_out_date)
    
    if "check_in_date" in update_data or "check_out_date" in update_data:
        if check_booking_overlap(db, booking.unit_id, new_check_in, new_check_out, booking_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="يوجد تداخل مع حجز آخر في هذه الفترة"
            )
    
    for field, value in update_data.items():
        if field == "status" and value:
            setattr(booking, field, value.value)
        else:
            setattr(booking, field, value)
    
    # تسجيل الموظف الذي عدل الحجز
    booking.updated_by_id = current_user.id
    
    db.commit()
    db.refresh(booking)
    
    # تسجيل نشاط تعديل الحجز
    service = EmployeePerformanceService(db)
    service.log_activity(
        employee_id=current_user.id,
        activity_type=ActivityType.BOOKING_UPDATED,
        entity_type="booking",
        entity_id=booking.id,
        description=f"تعديل حجز: {booking.guest_name}"
    )
    
    unit = booking.unit
    project = unit.project if unit else None
    
    return BookingResponse(
        id=booking.id,
        unit_id=booking.unit_id,
        guest_name=booking.guest_name,
        guest_phone=booking.guest_phone,
        check_in_date=booking.check_in_date,
        check_out_date=booking.check_out_date,
        total_price=booking.total_price,
        status=booking.status,
        notes=booking.notes,
        project_id=project.id if project else "",
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name if unit else "غير معروف",
        created_at=booking.created_at,
        updated_at=booking.updated_at
    )


@router.patch("/{booking_id}/status")
@router.patch("/{booking_id}/status/", response_model=BookingResponse)
async def update_booking_status(
    booking_id: str,
    status_data: BookingStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تغيير حالة الحجز"""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    old_status = booking.status
    new_status = status_data.status.value
    booking.status = new_status
    booking.updated_by_id = current_user.id
    db.commit()
    db.refresh(booking)
    
    # تسجيل النشاط حسب الحالة الجديدة
    service = EmployeePerformanceService(db)
    if new_status == "مكتمل":
        log_booking_completed(db, current_user.id, booking.id, float(booking.total_price))
    elif new_status == "ملغي":
        log_booking_cancelled(db, current_user.id, booking.id)
    elif new_status == "دخول":
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.BOOKING_CHECKED_IN,
            entity_type="booking",
            entity_id=booking.id
        )
    elif new_status == "خروج":
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.BOOKING_CHECKED_OUT,
            entity_type="booking",
            entity_id=booking.id
        )
    
    unit = booking.unit
    project = unit.project if unit else None
    
    return BookingResponse(
        id=booking.id,
        unit_id=booking.unit_id,
        guest_name=booking.guest_name,
        guest_phone=booking.guest_phone,
        check_in_date=booking.check_in_date,
        check_out_date=booking.check_out_date,
        total_price=booking.total_price,
        status=booking.status,
        notes=booking.notes,
        project_id=project.id if project else "",
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name if unit else "غير معروف",
        created_at=booking.created_at,
        updated_at=booking.updated_at
    )


@router.delete("/{booking_id}")
@router.delete("/{booking_id}/")
async def delete_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """حذف/إلغاء حجز"""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    db.delete(booking)
    db.commit()
    
    return {"message": "تم حذف الحجز بنجاح"}
