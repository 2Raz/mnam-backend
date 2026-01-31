"""
Router للتنبيهات - Alerts Router
تنبيهات ذكية للحالات المهمة
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import date, datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel
from enum import Enum

from ..database import get_db
from ..utils.dependencies import get_current_user
from ..models import User, Booking, Unit, Customer, Project, PricingPolicy


router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


# ============ Enums & Schemas ============

class AlertSeverity(str, Enum):
    CRITICAL = "critical"  # أحمر - عاجل
    WARNING = "warning"    # أصفر - تحذير
    INFO = "info"          # أزرق - معلومات
    SUCCESS = "success"    # أخضر - إيجابي


class AlertType(str, Enum):
    UNIT_NO_PRICING = "unit_no_pricing"
    UNPAID_BOOKING = "unpaid_booking"
    VIP_ARRIVING = "vip_arriving"
    LONG_MAINTENANCE = "long_maintenance"
    HIGH_CANCELLATION = "high_cancellation"
    UNIT_NEEDS_CLEANING = "unit_needs_cleaning"
    CHECKOUT_TODAY = "checkout_today"
    CHECKIN_TODAY = "checkin_today"
    LOW_OCCUPANCY = "low_occupancy"


class AlertItem(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    icon: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    action_label: Optional[str] = None
    action_url: Optional[str] = None
    created_at: datetime


class AlertsResponse(BaseModel):
    alerts: List[AlertItem]
    total: int
    critical_count: int
    warning_count: int


# ============ Alert Icons ============

ALERT_ICONS = {
    AlertType.UNIT_NO_PRICING: "💰",
    AlertType.UNPAID_BOOKING: "💳",
    AlertType.VIP_ARRIVING: "⭐",
    AlertType.LONG_MAINTENANCE: "🔧",
    AlertType.HIGH_CANCELLATION: "❌",
    AlertType.UNIT_NEEDS_CLEANING: "🧹",
    AlertType.CHECKOUT_TODAY: "👋",
    AlertType.CHECKIN_TODAY: "🏠",
    AlertType.LOW_OCCUPANCY: "📉",
}


# ============ Endpoints ============

@router.get("", response_model=AlertsResponse)
@router.get("/", response_model=AlertsResponse)
async def get_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    الحصول على التنبيهات الذكية
    
    التنبيهات تشمل:
    - وحدات بدون سياسة تسعير
    - حجوزات بدون دفع
    - عملاء VIP قادمين اليوم
    - وحدات في صيانة طويلة
    - نسبة إلغاءات عالية
    - وحدات تحتاج تنظيف
    - تسجيل وصول/مغادرة اليوم
    """
    alerts = []
    today = date.today()
    now = datetime.now()
    
    # 1. وحدات بدون سياسة تسعير
    units_no_pricing = db.query(Unit).filter(
        Unit.is_deleted == False,
        ~Unit.pricing_policy.has()
    ).all()
    
    for unit in units_no_pricing[:5]:  # أقصى 5
        alerts.append(AlertItem(
            id=f"no_pricing_{unit.id}",
            type=AlertType.UNIT_NO_PRICING.value,
            severity=AlertSeverity.WARNING.value,
            title=f"الوحدة {unit.unit_name} بدون سياسة تسعير",
            message="يجب إضافة سياسة تسعير للوحدة لتفعيل الحساب التلقائي للأسعار",
            icon=ALERT_ICONS[AlertType.UNIT_NO_PRICING],
            entity_type="unit",
            entity_id=unit.id,
            action_label="إضافة تسعير",
            action_url=f"/units/{unit.id}/pricing",
            created_at=now
        ))
    
    # 2. وحدات تحتاج تنظيف
    units_cleaning = db.query(Unit).filter(
        Unit.is_deleted == False,
        Unit.status == "تحتاج تنظيف"
    ).all()
    
    for unit in units_cleaning[:3]:
        alerts.append(AlertItem(
            id=f"cleaning_{unit.id}",
            type=AlertType.UNIT_NEEDS_CLEANING.value,
            severity=AlertSeverity.WARNING.value,
            title=f"🧹 الوحدة {unit.unit_name} تحتاج تنظيف",
            message="الوحدة بحاجة للتنظيف قبل الحجز القادم",
            icon=ALERT_ICONS[AlertType.UNIT_NEEDS_CLEANING],
            entity_type="unit",
            entity_id=unit.id,
            action_label="تحديث الحالة",
            action_url=f"/units/{unit.id}",
            created_at=now
        ))
    
    # 3. وحدات في صيانة طويلة (أكثر من 7 أيام)
    maintenance_threshold = today - timedelta(days=7)
    units_long_maintenance = db.query(Unit).filter(
        Unit.is_deleted == False,
        Unit.status == "صيانة",
        Unit.updated_at <= maintenance_threshold
    ).all()
    
    for unit in units_long_maintenance[:3]:
        days = (today - unit.updated_at.date()).days if unit.updated_at else 0
        alerts.append(AlertItem(
            id=f"maintenance_{unit.id}",
            type=AlertType.LONG_MAINTENANCE.value,
            severity=AlertSeverity.WARNING.value,
            title=f"الوحدة {unit.unit_name} في صيانة منذ {days} يوم",
            message="يجب مراجعة حالة الصيانة وتحديثها",
            icon=ALERT_ICONS[AlertType.LONG_MAINTENANCE],
            entity_type="unit",
            entity_id=unit.id,
            action_label="مراجعة",
            action_url=f"/units/{unit.id}",
            created_at=now
        ))
    
    # 4. تسجيل وصول اليوم
    checkins_today = db.query(Booking).filter(
        Booking.is_deleted == False,
        Booking.check_in_date == today,
        Booking.status.in_(["مؤكد"])
    ).all()
    
    for booking in checkins_today[:5]:
        alerts.append(AlertItem(
            id=f"checkin_{booking.id}",
            type=AlertType.CHECKIN_TODAY.value,
            severity=AlertSeverity.INFO.value,
            title=f"🏠 وصول {booking.guest_name} اليوم",
            message=f"تسجيل وصول للوحدة - تأكد من جاهزيتها",
            icon=ALERT_ICONS[AlertType.CHECKIN_TODAY],
            entity_type="booking",
            entity_id=booking.id,
            action_label="عرض الحجز",
            action_url=f"/bookings/{booking.id}",
            created_at=now
        ))
    
    # 5. تسجيل مغادرة اليوم
    checkouts_today = db.query(Booking).filter(
        Booking.is_deleted == False,
        Booking.check_out_date == today,
        Booking.status.in_(["مؤكد", "دخول"])
    ).all()
    
    for booking in checkouts_today[:5]:
        alerts.append(AlertItem(
            id=f"checkout_{booking.id}",
            type=AlertType.CHECKOUT_TODAY.value,
            severity=AlertSeverity.INFO.value,
            title=f"👋 مغادرة {booking.guest_name} اليوم",
            message=f"تسجيل مغادرة - تذكر تغيير حالة الوحدة",
            icon=ALERT_ICONS[AlertType.CHECKOUT_TODAY],
            entity_type="booking",
            entity_id=booking.id,
            action_label="عرض الحجز",
            action_url=f"/bookings/{booking.id}",
            created_at=now
        ))
    
    # 6. عملاء VIP قادمين (2+ حجوزات سابقة)
    vip_arrivals = db.query(Booking).join(Customer).filter(
        Booking.is_deleted == False,
        Booking.check_in_date == today,
        Booking.status.in_(["مؤكد"]),
        Customer.completed_booking_count >= 2
    ).all()
    
    for booking in vip_arrivals[:3]:
        alerts.append(AlertItem(
            id=f"vip_{booking.id}",
            type=AlertType.VIP_ARRIVING.value,
            severity=AlertSeverity.SUCCESS.value,
            title=f"⭐ عميل مميز: {booking.guest_name}",
            message=f"عميل لديه {booking.customer.completed_booking_count} حجوزات سابقة",
            icon=ALERT_ICONS[AlertType.VIP_ARRIVING],
            entity_type="booking",
            entity_id=booking.id,
            action_label="عرض الحجز",
            action_url=f"/bookings/{booking.id}",
            created_at=now
        ))
    
    # 7. نسبة إلغاءات عالية (أكثر من 20% هذا الأسبوع)
    week_start = today - timedelta(days=today.weekday())
    total_bookings_week = db.query(Booking).filter(
        func.date(Booking.created_at) >= week_start,
        Booking.is_deleted == False
    ).count()
    
    cancelled_week = db.query(Booking).filter(
        func.date(Booking.created_at) >= week_start,
        Booking.status == "ملغي"
    ).count()
    
    if total_bookings_week > 5 and cancelled_week > 0:
        cancellation_rate = (cancelled_week / total_bookings_week) * 100
        if cancellation_rate > 20:
            alerts.append(AlertItem(
                id="high_cancellation",
                type=AlertType.HIGH_CANCELLATION.value,
                severity=AlertSeverity.CRITICAL.value,
                title=f"⚠️ نسبة إلغاءات عالية: {cancellation_rate:.0f}%",
                message=f"تم إلغاء {cancelled_week} من أصل {total_bookings_week} حجز هذا الأسبوع",
                icon=ALERT_ICONS[AlertType.HIGH_CANCELLATION],
                entity_type=None,
                entity_id=None,
                action_label="تحليل الإلغاءات",
                action_url="/bookings?status=cancelled",
                created_at=now
            ))
    
    # ترتيب التنبيهات حسب الأهمية
    severity_order = {
        AlertSeverity.CRITICAL.value: 0,
        AlertSeverity.WARNING.value: 1,
        AlertSeverity.INFO.value: 2,
        AlertSeverity.SUCCESS.value: 3
    }
    alerts.sort(key=lambda x: severity_order.get(x.severity, 4))
    
    # حساب الإحصائيات
    critical_count = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL.value)
    warning_count = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING.value)
    
    return AlertsResponse(
        alerts=alerts,
        total=len(alerts),
        critical_count=critical_count,
        warning_count=warning_count
    )


@router.get("/summary")
@router.get("/summary/")
async def get_alerts_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """ملخص سريع للتنبيهات - للعرض في Dashboard"""
    today = date.today()
    
    # حساب الأعداد
    cleaning_count = db.query(Unit).filter(
        Unit.is_deleted == False,
        Unit.status == "تحتاج تنظيف"
    ).count()
    
    checkins_today = db.query(Booking).filter(
        Booking.is_deleted == False,
        Booking.check_in_date == today,
        Booking.status.in_(["مؤكد"])
    ).count()
    
    checkouts_today = db.query(Booking).filter(
        Booking.is_deleted == False,
        Booking.check_out_date == today,
        Booking.status.in_(["مؤكد", "دخول"])
    ).count()
    
    maintenance_count = db.query(Unit).filter(
        Unit.is_deleted == False,
        Unit.status == "صيانة"
    ).count()
    
    return {
        "cleaning_required": cleaning_count,
        "checkins_today": checkins_today,
        "checkouts_today": checkouts_today,
        "under_maintenance": maintenance_count,
        "total_actions": cleaning_count + checkins_today + checkouts_today
    }
