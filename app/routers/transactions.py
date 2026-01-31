from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal

from ..database import get_db
from ..models.transaction import Transaction
from ..models.project import Project
from ..models.unit import Unit
from ..models.booking import Booking
from ..schemas.transaction import (
    TransactionResponse, TransactionCreate, TransactionUpdate, 
    FinancialSummary, TeamAchievement, DailyChallenge, WeeklyPerformance, MonthlyHarvest
)
from ..utils.dependencies import get_current_user
from ..models.user import User

router = APIRouter(prefix="/api/transactions", tags=["المعاملات المالية"])


@router.get("")
@router.get("/", response_model=List[TransactionResponse])
async def get_all_transactions(
    project_id: Optional[str] = None,
    type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة المعاملات المالية مع فلترة اختيارية"""
    query = db.query(Transaction)
    
    if project_id:
        query = query.filter(Transaction.project_id == project_id)
    if type:
        query = query.filter(Transaction.type == type)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    
    transactions = query.order_by(Transaction.date.desc()).all()
    
    result = []
    for t in transactions:
        project = t.project
        unit = t.unit
        
        result.append(TransactionResponse(
            id=t.id,
            project_id=t.project_id,
            unit_id=t.unit_id,
            description=t.description,
            date=t.date,
            amount=t.amount,
            type=t.type,
            category=t.category,
            project_name=project.name if project else "غير معروف",
            unit_name=unit.unit_name if unit else None,
            created_at=t.created_at
        ))
    
    return result


@router.get("/summary")
@router.get("/summary/", response_model=FinancialSummary)
async def get_financial_summary(
    project_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على ملخص مالي"""
    query = db.query(Transaction)
    
    if project_id:
        query = query.filter(Transaction.project_id == project_id)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    
    income = query.filter(Transaction.type == "دخل").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar() or Decimal("0")
    
    expense = query.filter(Transaction.type == "صرف").with_entities(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).scalar() or Decimal("0")
    
    return FinancialSummary(
        total_income=income,
        total_expense=expense,
        net_profit=income - expense
    )


@router.get("/team-achievement")
@router.get("/team-achievement/", response_model=TeamAchievement)
async def get_team_achievement(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """رحلة إنجاز الفريق - إحصائيات يومية وأسبوعية وشهرية"""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = date(today.year, today.month, 1)
    
    total_units = db.query(Unit).count() or 1  # Avoid division by zero
    
    # ========== تحدي اليوم ==========
    # إشغال الوحدات اليوم
    today_occupancy = db.query(Booking).filter(
        Booking.check_in_date <= today,
        Booking.check_out_date > today,
        Booking.status.in_(["مؤكد", "دخول"])
    ).count()
    
    # ليالي الضيوف اليوم (عدد الحجوزات النشطة)
    today_guest_nights = today_occupancy
    
    # دخل اليوم
    today_income = db.query(func.coalesce(func.sum(Booking.total_price), 0)).filter(
        func.date(Booking.created_at) == today,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).scalar() or Decimal("0")
    
    # إلغاءات اليوم
    today_cancellations = db.query(Booking).filter(
        func.date(Booking.created_at) == today,
        Booking.status == "ملغي"
    ).count()
    
    daily_challenge = DailyChallenge(
        unit_occupancy=today_occupancy,
        guest_nights=today_guest_nights,
        today_income=today_income,
        total_cancellations=today_cancellations
    )
    
    # ========== أداء الأسبوع ==========
    # إجمالي الليالي هذا الأسبوع
    weekly_nights = db.query(Booking).filter(
        Booking.check_in_date >= week_start,
        Booking.check_in_date <= today,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).count()
    
    # نسبة الإشغال الأسبوعي (متوسط)
    days_in_week = (today - week_start).days + 1
    weekly_avg_occupancy = db.query(func.count(Booking.id)).filter(
        Booking.check_in_date >= week_start,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).scalar() or 0
    weekly_occupancy_rate = round((weekly_avg_occupancy / (total_units * days_in_week)) * 100, 1) if days_in_week > 0 else 0
    
    # تحصيل الإيرادات الأسبوعي
    weekly_revenue = db.query(func.coalesce(func.sum(Booking.total_price), 0)).filter(
        Booking.check_in_date >= week_start,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).scalar() or Decimal("0")
    
    # إلغاءات الأسبوع
    weekly_cancellations = db.query(Booking).filter(
        func.date(Booking.created_at) >= week_start,
        Booking.status == "ملغي"
    ).count()
    
    weekly_performance = WeeklyPerformance(
        total_nights=weekly_nights,
        weekly_occupancy_rate=min(weekly_occupancy_rate, 100),
        revenue_collection=weekly_revenue,
        total_cancellations=weekly_cancellations
    )
    
    # ========== الحصاد الشهري ==========
    # معدل الإشغال الشهري
    days_in_month = (today - month_start).days + 1
    monthly_bookings = db.query(func.count(Booking.id)).filter(
        Booking.check_in_date >= month_start,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).scalar() or 0
    monthly_occupancy_rate = round((monthly_bookings / (total_units * days_in_month)) * 100, 1) if days_in_month > 0 else 0
    
    # مبيعات الليالي الشهرية
    monthly_nights_sales = monthly_bookings
    
    # دخل المشاريع الشهري
    monthly_project_income = db.query(func.coalesce(func.sum(Booking.total_price), 0)).filter(
        Booking.check_in_date >= month_start,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).scalar() or Decimal("0")
    
    # إلغاءات الشهر
    monthly_cancellations = db.query(Booking).filter(
        func.date(Booking.created_at) >= month_start,
        Booking.status == "ملغي"
    ).count()
    
    monthly_harvest = MonthlyHarvest(
        monthly_occupancy_rate=min(monthly_occupancy_rate, 100),
        nights_sales=monthly_nights_sales,
        project_income=monthly_project_income,
        total_cancellations=monthly_cancellations
    )
    
    return TeamAchievement(
        daily_challenge=daily_challenge,
        weekly_performance=weekly_performance,
        monthly_harvest=monthly_harvest
    )


@router.get("/{transaction_id}")
@router.get("/{transaction_id}/", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على معاملة محددة"""
    t = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not t:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المعاملة غير موجودة"
        )
    
    project = t.project
    unit = t.unit
    
    return TransactionResponse(
        id=t.id,
        project_id=t.project_id,
        unit_id=t.unit_id,
        description=t.description,
        date=t.date,
        amount=t.amount,
        type=t.type,
        category=t.category,
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name if unit else None,
        created_at=t.created_at
    )


@router.post("")
@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    transaction_data: TransactionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """إضافة معاملة مالية جديدة"""
    # Verify project exists
    project = db.query(Project).filter(Project.id == transaction_data.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="المشروع غير موجود"
        )
    
    # Verify unit if provided
    unit = None
    if transaction_data.unit_id:
        unit = db.query(Unit).filter(Unit.id == transaction_data.unit_id).first()
        if not unit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="الوحدة غير موجودة"
            )
    
    new_transaction = Transaction(
        project_id=transaction_data.project_id,
        unit_id=transaction_data.unit_id,
        description=transaction_data.description,
        date=transaction_data.date,
        amount=transaction_data.amount,
        type=transaction_data.type.value,
        category=transaction_data.category
    )
    
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    return TransactionResponse(
        id=new_transaction.id,
        project_id=new_transaction.project_id,
        unit_id=new_transaction.unit_id,
        description=new_transaction.description,
        date=new_transaction.date,
        amount=new_transaction.amount,
        type=new_transaction.type,
        category=new_transaction.category,
        project_name=project.name,
        unit_name=unit.unit_name if unit else None,
        created_at=new_transaction.created_at
    )


@router.put("/{transaction_id}")
@router.put("/{transaction_id}/", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: str,
    transaction_data: TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديث معاملة مالية"""
    t = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not t:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المعاملة غير موجودة"
        )
    
    update_data = transaction_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "type" and value:
            setattr(t, field, value.value)
        else:
            setattr(t, field, value)
    
    db.commit()
    db.refresh(t)
    
    project = t.project
    unit = t.unit
    
    return TransactionResponse(
        id=t.id,
        project_id=t.project_id,
        unit_id=t.unit_id,
        description=t.description,
        date=t.date,
        amount=t.amount,
        type=t.type,
        category=t.category,
        project_name=project.name if project else "غير معروف",
        unit_name=unit.unit_name if unit else None,
        created_at=t.created_at
    )


@router.delete("/{transaction_id}")
@router.delete("/{transaction_id}/")
async def delete_transaction(
    transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """حذف معاملة مالية"""
    t = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not t:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المعاملة غير موجودة"
        )
    
    db.delete(t)
    db.commit()
    
    return {"message": "تم حذف المعاملة بنجاح"}


@router.get("/reports/export")
@router.get("/reports/export/")
async def export_financial_report(
    period: str = Query("monthly", description="daily, weekly, monthly"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تصدير تقرير مالي - يرجع بيانات JSON للتقرير"""
    today = date.today()
    
    if period == "daily":
        start_date = today
        period_label = f"تقرير يومي - {today.strftime('%Y-%m-%d')}"
    elif period == "weekly":
        start_date = today - timedelta(days=today.weekday())
        period_label = f"تقرير أسبوعي - من {start_date.strftime('%Y-%m-%d')} إلى {today.strftime('%Y-%m-%d')}"
    else:  # monthly
        start_date = date(today.year, today.month, 1)
        period_label = f"تقرير شهري - {today.strftime('%Y-%m')}"
    
    total_units = db.query(Unit).count() or 1
    
    # الحجوزات
    bookings = db.query(Booking).filter(
        Booking.check_in_date >= start_date,
        Booking.status.in_(["مؤكد", "دخول", "مكتمل"])
    ).all()
    
    total_bookings = len(bookings)
    total_revenue = sum(b.total_price or 0 for b in bookings)
    
    # الإلغاءات
    cancellations = db.query(Booking).filter(
        func.date(Booking.created_at) >= start_date,
        Booking.status == "ملغي"
    ).count()
    
    # نسبة الإشغال
    days_count = (today - start_date).days + 1
    occupancy_rate = round((total_bookings / (total_units * days_count)) * 100, 1) if days_count > 0 else 0
    
    # المعاملات المالية
    transactions = db.query(Transaction).filter(
        Transaction.date >= start_date
    ).all()
    
    income = sum(t.amount for t in transactions if t.type == "دخل")
    expenses = sum(t.amount for t in transactions if t.type == "صرف")
    
    return {
        "report_title": period_label,
        "generated_at": datetime.now().isoformat(),
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "summary": {
            "total_bookings": total_bookings,
            "total_revenue": float(total_revenue),
            "total_cancellations": cancellations,
            "occupancy_rate": min(occupancy_rate, 100),
            "transaction_income": float(income),
            "transaction_expenses": float(expenses),
            "net_profit": float(income - expenses)
        },
        "bookings": [
            {
                "id": b.id,
                "guest_name": b.guest_name,
                "check_in": b.check_in_date.isoformat() if b.check_in_date else None,
                "check_out": b.check_out_date.isoformat() if b.check_out_date else None,
                "total_price": float(b.total_price or 0),
                "status": b.status
            }
            for b in bookings[:50]  # Limit to 50 for performance
        ]
    }

