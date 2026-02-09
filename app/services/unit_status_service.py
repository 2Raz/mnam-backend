"""
Unit Status Service
خدمة حساب حالة الوحدة تلقائياً

المبدأ:
- حالة "محجوزة" محسوبة تلقائياً بناءً على وجود حجوزات نشطة
- باقي الحالات (متاحة، صيانة، تحتاج تنظيف، مخفية) يدوية
"""

from datetime import date
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_
import logging

logger = logging.getLogger(__name__)


def get_effective_unit_status(db: Session, unit_id: str) -> Tuple[str, bool]:
    """
    حساب الحالة الفعلية للوحدة بناءً على الحجوزات النشطة
    
    القواعد:
    1. إذا كان هناك حجز نشط (check_in <= today <= check_out) → "محجوزة"
    2. إذا كان هناك حجز قادم (check_in > today) وحالة الوحدة "متاحة" → "محجوزة"
    3. أي حالة يدوية أخرى (صيانة، تحتاج تنظيف، مخفية) تبقى كما هي
    
    Returns:
        Tuple[str, bool]: (الحالة الفعلية، هل يوجد حجوزات نشطة)
    """
    from ..models.unit import Unit
    from ..models.booking import Booking
    
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        return "غير موجودة", False
    
    today = date.today()
    
    # البحث عن حجوزات نشطة (مؤكدة أو قيد الإقامة)
    active_bookings = db.query(Booking).filter(
        and_(
            Booking.unit_id == unit_id,
            Booking.is_deleted == False,
            Booking.check_out_date >= today,
            Booking.status.in_(["مؤكد", "قيد الإقامة", "pending", "confirmed"])
        )
    ).all()
    
    has_active_bookings = len(active_bookings) > 0
    
    # إذا كانت الحالة اليدوية صيانة/تنظيف/مخفية، تبقى كما هي
    if unit.status in ["صيانة", "تحتاج تنظيف", "مخفية"]:
        return unit.status, has_active_bookings
    
    # إذا كان هناك حجوزات نشطة والحالة اليدوية "متاحة"
    if has_active_bookings:
        return "محجوزة", True
    
    # لا توجد حجوزات نشطة
    return "متاحة", False


def get_unit_display_status(db: Session, unit_id: str) -> dict:
    """
    الحصول على معلومات الحالة للعرض
    """
    from ..models.unit import Unit
    from ..models.booking import Booking
    
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        return {"error": "الوحدة غير موجودة"}
    
    effective_status, has_bookings = get_effective_unit_status(db, unit_id)
    
    today = date.today()
    
    # الحجز الحالي (إن وجد)
    current_booking = db.query(Booking).filter(
        and_(
            Booking.unit_id == unit_id,
            Booking.is_deleted == False,
            Booking.check_in_date <= today,
            Booking.check_out_date >= today,
            Booking.status.in_(["مؤكد", "قيد الإقامة"])
        )
    ).first()
    
    # عدد الحجوزات القادمة
    upcoming_bookings = db.query(Booking).filter(
        and_(
            Booking.unit_id == unit_id,
            Booking.is_deleted == False,
            Booking.check_in_date > today,
            Booking.status.in_(["مؤكد", "pending"])
        )
    ).count()
    
    return {
        "unit_id": unit_id,
        "unit_name": unit.unit_name,
        "manual_status": unit.status,  # الحالة المحفوظة في DB
        "effective_status": effective_status,  # الحالة الفعلية المحسوبة
        "has_active_bookings": has_bookings,
        "current_booking": {
            "id": current_booking.id,
            "guest_name": current_booking.guest_name,
            "check_out_date": str(current_booking.check_out_date)
        } if current_booking else None,
        "upcoming_bookings_count": upcoming_bookings,
        "can_accept_bookings": effective_status == "متاحة"
    }


def sync_unit_availability_with_computed_status(db: Session, unit_id: str) -> dict:
    """
    مزامنة التوفر مع Channex باستخدام الحالة المحسوبة
    """
    from ..services.availability_sync_service import AvailabilitySyncService
    
    effective_status, has_bookings = get_effective_unit_status(db, unit_id)
    
    logger.info(f"🔄 Syncing unit {unit_id} - Effective status: {effective_status}, Has bookings: {has_bookings}")
    
    service = AvailabilitySyncService(db)
    return service.sync_unit_availability(unit_id)
