from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List

from ..database import get_db
from ..models.booking import Booking
from ..models.unit import Unit
from ..schemas.dashboard import (
    DashboardSummary, DashboardKpis, TodayFocus, 
    TodayFocusItem, UpcomingBookingSummary, EmployeePerformance
)
from ..utils.dependencies import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/dashboard", tags=["لوحة التحكم"])


@router.get("")
@router.get("/")
@router.get("/summary")
@router.get("/summary/", response_model=DashboardSummary)
async def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على ملخص لوحة التحكم"""
    today = date.today()
    now = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    
    # Current month start/end
    month_start = date(now.year, now.month, 1)
    if now.month == 12:
        month_end = date(now.year + 1, 1, 1)
    else:
        month_end = date(now.year, now.month + 1, 1)
    
    # KPIs
    current_month_revenue = db.query(
        func.coalesce(func.sum(Booking.total_price), 0)
    ).filter(
        Booking.check_in_date >= month_start,
        Booking.check_in_date < month_end,
        Booking.status.in_(["مؤكد", "مكتمل"])
    ).scalar() or Decimal("0")
    
    current_guests = db.query(Booking).filter(
        Booking.check_in_date <= today,
        Booking.check_out_date > today,
        Booking.status.in_(["مؤكد"])
    ).count()
    
    total_units = db.query(Unit).count()
    
    # الوحدات المحجوزة اليوم
    booked_units = db.query(Booking).filter(
        Booking.check_in_date <= today,
        Booking.check_out_date > today,
        Booking.status.in_(["مؤكد", "دخول"])
    ).count()
    
    # نسبة الإشغال
    occupancy_rate = (booked_units / total_units * 100) if total_units > 0 else 0.0
    
    # الوحدات تحت التنظيف
    cleaning_units = db.query(Unit).filter(Unit.status == "تحتاج تنظيف").count()
    
    # الوحدات تحت الصيانة
    maintenance_units = db.query(Unit).filter(Unit.status == "صيانة").count()
    
    kpis = DashboardKpis(
        current_month_revenue=current_month_revenue,
        current_guests=current_guests,
        total_units=total_units,
        occupancy_rate=round(occupancy_rate, 1),
        booked_units=booked_units,
        cleaning_units=cleaning_units,
        maintenance_units=maintenance_units
    )
    
    # Today's arrivals (فقط اللي ما صار لهم check-in)
    arrivals = db.query(Booking).filter(
        Booking.check_in_date == today,
        Booking.status.in_(["مؤكد", "قيد الانتظار"])
    ).all()
    
    arrival_items = []
    pending_checkins = []
    for b in arrivals:
        unit = b.unit
        project = unit.project if unit else None
        item = TodayFocusItem(
            booking_id=b.id,
            guest_name=b.guest_name,
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else "غير معروف"
        )
        arrival_items.append(item)
        # إذا ما صار check-in
        if b.status != "دخول":
            pending_checkins.append(item)
    
    # Today's departures
    departures = db.query(Booking).filter(
        Booking.check_out_date == today,
        Booking.status.in_(["مؤكد", "دخول"])
    ).all()
    
    departure_items = []
    for b in departures:
        unit = b.unit
        project = unit.project if unit else None
        departure_items.append(TodayFocusItem(
            booking_id=b.id,
            guest_name=b.guest_name,
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else "غير معروف"
        ))
    
    today_focus = TodayFocus(
        arrivals=arrival_items,
        departures=departure_items,
        pending_checkins=pending_checkins
    )
    
    # Upcoming bookings (next 7 days)
    upcoming_date = today + timedelta(days=7)
    upcoming = db.query(Booking).filter(
        Booking.check_in_date > today,
        Booking.check_in_date <= upcoming_date,
        Booking.status.in_(["مؤكد", "قيد الانتظار"])
    ).order_by(Booking.check_in_date).limit(10).all()
    
    upcoming_items = []
    for b in upcoming:
        unit = b.unit
        project = unit.project if unit else None
        upcoming_items.append(UpcomingBookingSummary(
            booking_id=b.id,
            guest_name=b.guest_name,
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else "غير معروف",
            check_in_date=str(b.check_in_date),
            total_price=b.total_price
        ))
    
    # إحصائيات الموظف
    # الحجوزات اليومية
    daily_bookings = db.query(Booking).filter(
        func.date(Booking.created_at) == today
    ).count()
    
    daily_completed = db.query(Booking).filter(
        func.date(Booking.created_at) == today,
        Booking.status.in_(["مكتمل", "دخول", "خروج"])
    ).count()
    
    # الحجوزات الأسبوعية
    weekly_bookings = db.query(Booking).filter(
        func.date(Booking.created_at) >= week_start
    ).count()
    
    weekly_completed = db.query(Booking).filter(
        func.date(Booking.created_at) >= week_start,
        Booking.status.in_(["مكتمل", "دخول", "خروج"])
    ).count()
    
    employee_performance = EmployeePerformance(
        daily_bookings=daily_bookings,
        daily_completed=daily_completed,
        daily_rate=round((daily_completed / daily_bookings * 100) if daily_bookings > 0 else 0, 1),
        weekly_bookings=weekly_bookings,
        weekly_completed=weekly_completed,
        weekly_rate=round((weekly_completed / weekly_bookings * 100) if weekly_bookings > 0 else 0, 1)
    )
    
    return DashboardSummary(
        kpis=kpis,
        today_focus=today_focus,
        upcoming_bookings=upcoming_items,
        employee_performance=employee_performance
    )
