from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import OperationalError
from typing import List, Optional
from datetime import date, timedelta
from decimal import Decimal
import json
import logging

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
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType
from ..models.channel_integration import ExternalMapping, ChannelConnection, ConnectionStatus
from ..services.outbox_worker import enqueue_availability_update
from ..utils.db_helpers import acquire_row_lock, is_postgres

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bookings", tags=["الحجوزات"])


def _sync_availability_to_channex(db: Session, unit_id: str):
    """
    مزامنة التوفر مع Channex بعد تغيير الحجوزات.
    يتم إنشاء حدث في Outbox ليتم معالجته لاحقاً بواسطة Worker.
    """
    try:
        # البحث عن الـ mapping للوحدة
        mapping = db.query(ExternalMapping).join(ChannelConnection).filter(
            ExternalMapping.unit_id == unit_id,
            ExternalMapping.is_active == True,
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        ).first()
        
        if mapping:
            enqueue_availability_update(
                db=db,
                unit_id=unit_id,
                connection_id=mapping.connection_id,
                days_ahead=365
            )
    except Exception as e:
        # لا نريد أن يفشل الحجز بسبب فشل المزامنة
        import logging
        logging.getLogger(__name__).warning(f"Failed to sync availability to Channex: {e}")


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


def validate_booking_data(
    check_in: date,
    check_out: date,
    guest_name: Optional[str] = None,
    guest_phone: Optional[str] = None,
    total_price: Optional[Decimal] = None,
    exclude_booking_id: Optional[str] = None,
    allow_past_dates: bool = False,
    max_advance_days: int = 730,  # سنتين
    max_duration_nights: int = 365  # سنة
) -> tuple:
    """
    تحقق شامل من صحة بيانات الحجز.
    
    يُرجع: (is_valid, error_message)
    """
    errors = []
    today = date.today()
    
    # ===== 1. التحقق من التواريخ المفقودة =====
    if not check_in:
        errors.append("تاريخ الوصول مطلوب")
    if not check_out:
        errors.append("تاريخ المغادرة مطلوب")
    
    if errors:
        return False, " | ".join(errors)
    
    # ===== 2. التحقق من صحة نطاق التواريخ =====
    if check_out <= check_in:
        return False, "تاريخ المغادرة يجب أن يكون بعد تاريخ الوصول"
    
    # ===== 3. التحقق من التواريخ في الماضي =====
    if not allow_past_dates:
        if check_out < today:
            return False, f"لا يمكن إنشاء حجز بتاريخ مغادرة في الماضي ({check_out})"
        # السماح بحجوزات بدأت في الماضي ولكن لم تنتهِ بعد
        # if check_in < today:
        #     return False, f"لا يمكن إنشاء حجز بتاريخ وصول في الماضي ({check_in})"
    
    # ===== 4. التحقق من التواريخ البعيدة جداً =====
    max_future_date = today + timedelta(days=max_advance_days)
    if check_in > max_future_date:
        return False, f"لا يمكن الحجز لأكثر من {max_advance_days // 365} سنة مقدماً"
    
    # ===== 5. التحقق من مدة الإقامة =====
    duration = (check_out - check_in).days
    
    if duration < 1:
        return False, "مدة الإقامة يجب أن تكون ليلة واحدة على الأقل"
    
    if duration > max_duration_nights:
        return False, f"مدة الإقامة طويلة جداً ({duration} ليلة). الحد الأقصى {max_duration_nights} ليلة"
    
    # ===== 6. التحقق من السعر =====
    if total_price is not None:
        try:
            price = float(total_price)
            if price < 0:
                return False, "السعر لا يمكن أن يكون سالباً"
            
            # تحذير للأسعار المرتفعة جداً (أكثر من مليون لليلة)
            price_per_night = price / duration if duration > 0 else price
            if price_per_night > 1000000:
                return False, f"السعر مرتفع بشكل غير منطقي ({price_per_night:.0f} ريال/ليلة)"
        except (ValueError, TypeError):
            pass  # السعر غير محدد - سيتم حسابه لاحقاً
    
    # ===== 7. التحقق من اسم الضيف =====
    if guest_name is not None:
        clean_name = guest_name.strip() if guest_name else ""
        if len(clean_name) < 2:
            return False, "اسم الضيف مطلوب (حرفين على الأقل)"
        if len(clean_name) > 100:
            return False, "اسم الضيف طويل جداً (الحد الأقصى 100 حرف)"
    
    # ===== 8. التحقق من رقم الجوال =====
    if guest_phone is not None:
        phone = guest_phone.strip() if guest_phone else ""
        if phone and len(phone) < 9:
            return False, "رقم الجوال غير صالح (9 أرقام على الأقل)"
        if phone and len(phone) > 20:
            return False, "رقم الجوال طويل جداً"
    
    return True, None


def to_booking_response(
    booking: Booking,
    unit: Optional[Unit] = None,
    project: Optional[Project] = None,
    customer: Optional[Customer] = None
) -> BookingResponse:
    """
    Helper function to build BookingResponse including all channel/source fields.
    Prevents code duplication across all booking endpoints.
    """
    # Get relationships if not provided
    if unit is None:
        unit = booking.unit
    if project is None and unit:
        project = unit.project
    if customer is None and booking.customer_id:
        customer = booking.customer
    
    # Parse channel_data from JSON string to dict
    channel_data = None
    if booking.channel_data:
        try:
            if isinstance(booking.channel_data, str):
                channel_data = json.loads(booking.channel_data)
            else:
                channel_data = booking.channel_data
        except (json.JSONDecodeError, TypeError):
            channel_data = {"raw": booking.channel_data}
    
    # Determine source_type from channel_source
    source_type = "manual"
    if hasattr(booking, 'source_type') and booking.source_type:
        source_type = booking.source_type
    elif booking.channel_source and booking.channel_source not in ["direct", "Direct"]:
        source_type = "channex"
    
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
        customer_id=booking.customer_id,
        customer_name=customer.name if customer else None,
        customer_is_banned=customer.is_banned if customer else False,
        # Channel Integration Fields
        source_type=source_type,
        channel_source=booking.channel_source or "direct",
        external_reservation_id=booking.external_reservation_id,
        external_revision_id=booking.external_revision_id,
        channel_data=channel_data,
        guest_email=booking.guest_email,
        created_at=booking.created_at,
        updated_at=booking.updated_at
    )


@router.get("")
@router.get("/", response_model=List[BookingResponse])
async def get_all_bookings(
    channel_source: Optional[str] = Query(None, description="تصفية حسب القناة (airbnb, booking.com, etc.)"),
    source_type: Optional[str] = Query(None, description="تصفية حسب المصدر (manual, channex, direct_api)"),
    has_external: Optional[bool] = Query(None, description="تصفية الحجوزات التي لها external_reservation_id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    الحصول على قائمة جميع الحجوزات
    
    Filters:
    - channel_source: airbnb, booking.com, gathern, direct, etc.
    - source_type: manual, channex, direct_api
    - has_external: true/false - للحجوزات الخارجية فقط
    """
    query = db.query(Booking)
    
    # Apply filters
    if channel_source:
        query = query.filter(Booking.channel_source == channel_source)
    
    if source_type:
        # Note: source_type may not exist in DB yet, fall back to channel_source logic
        if hasattr(Booking, 'source_type') and source_type:
            query = query.filter(Booking.source_type == source_type)
        elif source_type == "manual":
            query = query.filter(
                or_(
                    Booking.channel_source == "direct",
                    Booking.channel_source.is_(None)
                )
            )
        elif source_type == "channex":
            query = query.filter(
                Booking.channel_source.notin_(["direct", None])
            )
    
    if has_external is not None:
        if has_external:
            query = query.filter(Booking.external_reservation_id.isnot(None))
        else:
            query = query.filter(Booking.external_reservation_id.is_(None))
    
    bookings = query.order_by(Booking.check_in_date.desc()).all()
    
    return [to_booking_response(b) for b in bookings]


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
    
    return [to_booking_response(b) for b in bookings]


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
    
    return to_booking_response(booking)


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
    - يتم حساب السعر تلقائياً عبر Pricing Engine إذا لم يتم تحديده
    - يتم تخزين مصدر الحجز بصيغة "المنصة: X"
    """
    from ..services.pricing_engine import PricingEngine
    
    # ========== قفل الوحدة لمنع Race Condition ==========
    # نستخدم nowait=True لفشل سريع إذا الوحدة مقفلة
    try:
        unit = acquire_row_lock(
            db, Unit, 
            Unit.id == booking_data.unit_id, 
            nowait=True
        )
    except OperationalError as e:
        # الوحدة مقفلة من طلب آخر
        logger.warning(f"Lock contention on unit {booking_data.unit_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="الوحدة مشغولة حالياً بطلب آخر، يرجى المحاولة لاحقاً"
        )
    
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="الوحدة غير موجودة"
        )
    
    # ========== تنظيف بيانات العميل ==========
    clean_name = sanitize_name(booking_data.guest_name)
    normalized_phone = normalize_phone(booking_data.guest_phone or "")
    
    # ========== التحقق الشامل من صحة البيانات ==========
    is_valid, error_msg = validate_booking_data(
        check_in=booking_data.check_in_date,
        check_out=booking_data.check_out_date,
        guest_name=clean_name,
        guest_phone=normalized_phone,
        total_price=booking_data.total_price,
        allow_past_dates=False,
        max_advance_days=730,  # سنتين
        max_duration_nights=365  # سنة
    )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # ========== التحقق من وجود رقم جوال ==========
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="رقم جوال الضيف مطلوب"
        )
    
    # ========== التحقق من تداخل الحجوزات (آمن الآن لأن الوحدة مقفلة) ==========
    if check_booking_overlap(db, booking_data.unit_id, booking_data.check_in_date, booking_data.check_out_date):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="يوجد تداخل مع حجز آخر في هذه الفترة"
        )
    
    # ========== حساب السعر التلقائي ==========
    final_price = booking_data.total_price
    
    # إذا لم يتم تحديد السعر أو كان صفراً، نحسبه تلقائياً
    if final_price is None or float(final_price) <= 0:
        pricing_engine = PricingEngine(db)
        
        try:
            price_result = pricing_engine.compute_booking_total(
                unit_id=booking_data.unit_id,
                check_in=booking_data.check_in_date,
                check_out=booking_data.check_out_date,
                apply_realtime_discount_for_today=False
            )
            
            if price_result:
                final_price = Decimal(str(price_result["final_total"]))
            else:
                # Fallback: حساب محلي باستخدام أسعار الوحدة
                final_price = calculate_booking_price(
                    unit, 
                    booking_data.check_in_date, 
                    booking_data.check_out_date
                )
        except Exception as e:
            # محاولة حساب محلي كـ fallback
            try:
                final_price = calculate_booking_price(
                    unit, 
                    booking_data.check_in_date, 
                    booking_data.check_out_date
                )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"فشل في حساب سعر الحجز: {str(e)}"
                )
    
    # ========== التحقق من السعر النهائي ==========
    if final_price is None or float(final_price) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لم يتم تحديد سعر الحجز أو فشل حسابه تلقائياً"
        )
    
    # ========== معالجة مصدر الحجز ==========
    # تحويل المصدر لصيغة ثابتة: "المنصة: X"
    raw_source = booking_data.channel_source or ""
    raw_source = raw_source.strip()
    
    # قائمة المصادر المعروفة
    KNOWN_PLATFORMS = {
        'direct': 'مباشر',
        'مباشر': 'مباشر',
        'airbnb': 'Airbnb',
        'booking.com': 'Booking.com',
        'booking': 'Booking.com',
        'expedia': 'Expedia',
        'agoda': 'Agoda',
        'gathern': 'جذرن',
        'جذرن': 'جذرن',
        'other_ota': 'OTA',
        'unknown': 'غير معروف',
    }
    
    # تحويل المصدر
    if not raw_source:
        formatted_source = "المنصة: مباشر"
    else:
        # التحقق إذا كان المصدر بالصيغة الصحيحة بالفعل
        if raw_source.startswith("المنصة:"):
            formatted_source = raw_source
        else:
            # البحث عن المصدر في القائمة المعروفة
            platform_name = KNOWN_PLATFORMS.get(raw_source.lower(), raw_source)
            formatted_source = f"المنصة: {platform_name}"
    
    # ========== Auto Customer Sync (Upsert) ==========
    booking_amount = float(final_price)
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
        total_price=final_price,  # السعر المحسوب تلقائياً أو المدخل
        status=booking_data.status.value,
        notes=booking_data.notes,
        created_by_id=current_user.id,
        # مصدر الحجز بالصيغة الثابتة
        channel_source=formatted_source,
    )
    
    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    
    # ========== تسجيل النشاطات ==========
    log_booking_created(db, current_user.id, new_booking.id, booking_amount)
    
    # تسجيل نشاط إضافة عميل جديد إذا تم إنشاؤه
    if is_new_customer:
        log_customer_created(db, current_user.id, customer.id)
    
    # ========== تسجيل في سجل الأنشطة (AuditLog) ==========
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.BOOKING,
        entity_id=new_booking.id,
        entity_name=f"حجز {clean_name} - {unit.unit_name}",
        description=f"إنشاء حجز جديد للضيف {clean_name} في {unit.unit_name} من {booking_data.check_in_date} إلى {booking_data.check_out_date}",
        new_values={
            "guest_name": clean_name,
            "unit_name": unit.unit_name,
            "check_in_date": str(booking_data.check_in_date),
            "check_out_date": str(booking_data.check_out_date),
            "total_price": float(final_price),
            "status": booking_data.status.value,
            "channel_source": formatted_source
        }
    )
    
    # ========== مزامنة التوفر مع Channex ==========
    _sync_availability_to_channex(db, booking_data.unit_id)
    
    return to_booking_response(new_booking, unit=unit, project=project, customer=customer)


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
    new_guest_name = update_data.get("guest_name", booking.guest_name)
    new_guest_phone = update_data.get("guest_phone", booking.guest_phone)
    new_total_price = update_data.get("total_price", booking.total_price)
    
    # ========== التحقق الشامل من صحة البيانات ==========
    if "check_in_date" in update_data or "check_out_date" in update_data or \
       "guest_name" in update_data or "guest_phone" in update_data or "total_price" in update_data:
        
        is_valid, error_msg = validate_booking_data(
            check_in=new_check_in,
            check_out=new_check_out,
            guest_name=new_guest_name if "guest_name" in update_data else None,
            guest_phone=new_guest_phone if "guest_phone" in update_data else None,
            total_price=new_total_price if "total_price" in update_data else None,
            exclude_booking_id=booking_id,
            allow_past_dates=True,  # السماح بتعديل حجوزات قديمة
            max_advance_days=730,
            max_duration_nights=365
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
    
    # ========== التحقق من تداخل الحجوزات ==========
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
    
    # ========== تسجيل في سجل الأنشطة (AuditLog) ==========
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.BOOKING,
        entity_id=booking.id,
        entity_name=f"حجز {booking.guest_name}",
        description=f"تحديث بيانات حجز {booking.guest_name}",
        new_values=update_data
    )
    
    # ========== مزامنة التوفر مع Channex إذا تغيرت التواريخ أو الوحدة ==========
    if "check_in_date" in update_data or "check_out_date" in update_data or "unit_id" in update_data:
        _sync_availability_to_channex(db, booking.unit_id)
    
    return to_booking_response(booking)


@router.patch("/{booking_id}/status")
@router.patch("/{booking_id}/status/", response_model=BookingResponse)
async def update_booking_status(
    booking_id: str,
    status_data: BookingStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تغيير حالة الحجز"""
    # قفل الحجز لمنع تغييرات متزامنة
    booking = acquire_row_lock(db, Booking, Booking.id == booking_id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    old_status = booking.status
    new_status = status_data.status.value
    today = date.today()
    
    # ========== التحقق من صحة تغيير الحالة ==========
    
    # 1. لا يمكن تسجيل الدخول قبل تاريخ الوصول
    if new_status == "دخول":
        if booking.check_in_date > today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"لا يمكن تسجيل الدخول قبل تاريخ الوصول ({booking.check_in_date}). اليوم هو {today}"
            )
        # التحقق من أن الحالة الحالية مناسبة
        if old_status not in ["مؤكد", "confirmed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"لا يمكن تسجيل الدخول من حالة '{old_status}'. يجب أن يكون الحجز مؤكداً أولاً"
            )
    
    # 2. لا يمكن تسجيل الخروج قبل تسجيل الدخول
    if new_status in ["خروج", "مكتمل"]:
        if old_status not in ["دخول", "checked_in"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"لا يمكن تسجيل الخروج قبل تسجيل الدخول. الحالة الحالية: '{old_status}'"
            )
    
    # 3. لا يمكن تأكيد حجز ملغي
    if new_status == "مؤكد" and old_status in ["ملغي", "cancelled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لا يمكن تأكيد حجز ملغي. يرجى إنشاء حجز جديد"
        )
    
    # 4. تحذير إذا كان تاريخ المغادرة قد مضى ولم يتم الخروج
    if new_status == "دخول" and booking.check_out_date < today:
        # السماح ولكن مع تحذير في السجلات
        import logging
        logging.getLogger(__name__).warning(
            f"تسجيل دخول متأخر للحجز {booking_id}: تاريخ المغادرة ({booking.check_out_date}) قد مضى"
        )
    
    booking.status = new_status
    booking.updated_by_id = current_user.id
    db.commit()
    db.refresh(booking)
    
    # تسجيل النشاط حسب الحالة الجديدة
    service = EmployeePerformanceService(db)
    audit_activity_type = None
    audit_description = ""
    
    if new_status == "مكتمل":
        log_booking_completed(db, current_user.id, booking.id, float(booking.total_price))
        # تغيير حالة الوحدة إلى "تحتاج تنظيف" تلقائياً
        _update_unit_status_on_checkout(db, booking, current_user)
        audit_activity_type = AuditActivityType.BOOKING_CHECKOUT
        audit_description = f"اكتمال حجز {booking.guest_name}"
    elif new_status == "ملغي":
        log_booking_cancelled(db, current_user.id, booking.id)
        audit_activity_type = AuditActivityType.BOOKING_CANCEL
        audit_description = f"إلغاء حجز {booking.guest_name}"
    elif new_status == "مؤكد":
        audit_activity_type = AuditActivityType.BOOKING_CONFIRM
        audit_description = f"تأكيد حجز {booking.guest_name}"
    elif new_status == "دخول":
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.BOOKING_CHECKED_IN,
            entity_type="booking",
            entity_id=booking.id
        )
        audit_activity_type = AuditActivityType.BOOKING_CHECKIN
        audit_description = f"تسجيل وصول {booking.guest_name}"
    elif new_status == "خروج":
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.BOOKING_CHECKED_OUT,
            entity_type="booking",
            entity_id=booking.id
        )
        # تغيير حالة الوحدة إلى "تحتاج تنظيف" تلقائياً
        _update_unit_status_on_checkout(db, booking, current_user)
        audit_activity_type = AuditActivityType.BOOKING_CHECKOUT
        audit_description = f"تسجيل مغادرة {booking.guest_name}"
    
    # ========== تسجيل في سجل الأنشطة (AuditLog) ==========
    if audit_activity_type:
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=audit_activity_type,
            entity_type=AuditEntityType.BOOKING,
            entity_id=booking.id,
            entity_name=f"حجز {booking.guest_name}",
            description=audit_description,
            old_values={"status": old_status},
            new_values={"status": new_status}
        )
    
    # ========== مزامنة التوفر مع Channex إذا تغيرت الحالة لملغي أو أي حالة مهمة ==========
    if new_status in ["ملغي", "مؤكد", "مكتمل"]:
        _sync_availability_to_channex(db, booking.unit_id)
    
    return to_booking_response(booking)


def _update_unit_status_on_checkout(db: Session, booking: Booking, current_user: User):
    """
    تغيير حالة الوحدة إلى 'تحتاج تنظيف' تلقائياً عند Checkout
    وإنشاء إشعار للموظفين
    """
    from ..models.notification import Notification, NotificationType
    from ..models.unit import UnitStatus
    
    unit = db.query(Unit).filter(Unit.id == booking.unit_id).first()
    if not unit:
        return
    
    # تغيير حالة الوحدة
    old_status = unit.status
    unit.status = UnitStatus.CLEANING.value
    unit.updated_by_id = current_user.id
    
    # إنشاء إشعار لجميع المستخدمين
    notification = Notification(
        user_id=None,  # Broadcast to all
        type=NotificationType.UNIT_NEEDS_CLEANING.value,
        title=f"🧹 الوحدة {unit.unit_name} تحتاج تنظيف",
        message=f"تم تسجيل مغادرة الضيف {booking.guest_name}. الوحدة بحاجة للتنظيف.",
        entity_type="unit",
        entity_id=unit.id
    )
    db.add(notification)
    db.commit()


@router.delete("/{booking_id}")
@router.delete("/{booking_id}/")
async def delete_booking(
    booking_id: str,
    permanent: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    حذف/إلغاء حجز
    - permanent=false (افتراضي): Soft Delete
    - permanent=true: حذف نهائي (للمدير فقط)
    """
    from datetime import datetime
    
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود"
        )
    
    if permanent:
        if current_user.role not in ['admin', 'system_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحذف النهائي متاح للمدير فقط"
            )
        # حفظ بيانات الحجز قبل الحذف
        booking_name = f"حجز {booking.guest_name}"
        booking_id_temp = booking.id
        
        # تسجيل في سجل الأنشطة قبل الحذف
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.PERMANENT_DELETE,
            entity_type=AuditEntityType.BOOKING,
            entity_id=booking_id_temp,
            entity_name=booking_name,
            description=f"حذف نهائي لحجز: {booking.guest_name}"
        )
        unit_id = booking.unit_id  # حفظ قبل الحذف
        db.delete(booking)
        db.commit()
        # مزامنة التوفر مع Channex
        _sync_availability_to_channex(db, unit_id)
        return {"message": "تم حذف الحجز نهائياً"}
    else:
        unit_id = booking.unit_id
        booking.is_deleted = True
        booking.deleted_at = datetime.utcnow()
        booking.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.BOOKING,
            entity_id=booking.id,
            entity_name=f"حجز {booking.guest_name}",
            description=f"حذف حجز: {booking.guest_name}"
        )
        # مزامنة التوفر مع Channex
        _sync_availability_to_channex(db, unit_id)
        return {"message": "تم حذف الحجز بنجاح"}


@router.patch("/{booking_id}/restore")
@router.patch("/{booking_id}/restore/")
async def restore_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """استعادة حجز محذوف"""
    booking = db.query(Booking).filter(
        Booking.id == booking_id, 
        Booking.is_deleted == True
    ).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الحجز غير موجود أو غير محذوف"
        )
    
    booking.is_deleted = False
    booking.deleted_at = None
    booking.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.BOOKING,
        entity_id=booking.id,
        entity_name=f"حجز {booking.guest_name}",
        description=f"استعادة حجز: {booking.guest_name}"
    )
    
    return {"message": "تم استعادة الحجز بنجاح"}
