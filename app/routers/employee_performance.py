"""
API لنظام تتبع أداء الموظفين
Employee Performance Tracking API
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date, timedelta

from ..database import get_db
from ..models.user import User, UserRole
from ..models.employee_performance import EmployeeTarget
from ..schemas.employee_performance import (
    ActivityLogResponse, ActivityLogListResponse,
    EmployeeTargetCreate, EmployeeTargetUpdate, EmployeeTargetResponse,
    PerformanceSummaryResponse, EmployeeKPIsResponse,
    EmployeeDashboardResponse, TeamPerformanceOverview,
    SetTargetRequest
)
from ..services.employee_performance_service import EmployeePerformanceService
from ..utils.dependencies import get_current_user

router = APIRouter(prefix="/api/employee-performance", tags=["Employee Performance"])


# ======== لوحة تحكم الموظف ========

@router.get("/my-dashboard")
@router.get("/my-dashboard/")
async def get_my_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على لوحة تحكم الموظف الحالي"""
    service = EmployeePerformanceService(db)
    return service.get_employee_dashboard(current_user.id)


@router.get("/my-activities")
@router.get("/my-activities/")
async def get_my_activities(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على أنشطتي"""
    service = EmployeePerformanceService(db)
    return service.get_employee_activities(
        current_user.id, start_date, end_date, page=page, page_size=page_size
    )


@router.get("/my-target")
@router.get("/my-target/")
async def get_my_current_target(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على هدفي الحالي"""
    service = EmployeePerformanceService(db)
    target = service.get_current_target(current_user.id)
    if not target:
        return {"message": "لا يوجد هدف محدد حالياً", "target": None}
    
    achievement = service.calculate_target_achievement(current_user.id, target)
    return {
        "target": target,
        "achievement_rate": achievement
    }


# ======== لوحة تحكم المدير ========

@router.get("/team-overview")
@router.get("/team-overview/")
async def get_team_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """نظرة عامة على أداء الفريق (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = EmployeePerformanceService(db)
    return service.get_team_overview()


@router.get("/employee/{employee_id}/dashboard")
@router.get("/employee/{employee_id}/dashboard/")
async def get_employee_dashboard(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """لوحة تحكم موظف معين (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = EmployeePerformanceService(db)
    dashboard = service.get_employee_dashboard(employee_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    return dashboard


@router.get("/employee/{employee_id}/activities")
@router.get("/employee/{employee_id}/activities/")
async def get_employee_activities(
    employee_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """أنشطة موظف معين (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = EmployeePerformanceService(db)
    return service.get_employee_activities(
        employee_id, start_date, end_date, page=page, page_size=page_size
    )


# ======== إدارة الأهداف ========

@router.post("/targets")
@router.post("/targets/")
async def set_employee_target(
    request: SetTargetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """تحديد هدف لموظف (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    # التحقق من وجود الموظف
    employee = db.query(User).filter(User.id == request.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    
    # التحقق من صلاحية تحديد هدف لهذا الموظف
    if employee.role_level >= current_user.role_level and not current_user.is_system_owner:
        raise HTTPException(status_code=403, detail="لا يمكنك تحديد هدف لموظف بنفس رتبتك أو أعلى")
    
    service = EmployeePerformanceService(db)
    
    # تجهيز قيم الهدف
    target_values = {}
    if request.target_bookings is not None:
        target_values["target_bookings"] = request.target_bookings
    if request.target_booking_revenue is not None:
        target_values["target_booking_revenue"] = request.target_booking_revenue
    if request.target_new_customers is not None:
        target_values["target_new_customers"] = request.target_new_customers
    if request.target_completion_rate is not None:
        target_values["target_completion_rate"] = request.target_completion_rate
    if request.target_new_owners is not None:
        target_values["target_new_owners"] = request.target_new_owners
    if request.target_new_projects is not None:
        target_values["target_new_projects"] = request.target_new_projects
    if request.target_new_units is not None:
        target_values["target_new_units"] = request.target_new_units
    if request.notes is not None:
        target_values["notes"] = request.notes
    
    target = service.set_target(
        employee_id=request.employee_id,
        set_by_id=current_user.id,
        period=request.period,
        start_date=request.start_date,
        end_date=request.end_date,
        **target_values
    )
    
    return {
        "message": "تم تحديد الهدف بنجاح",
        "target": target
    }


@router.get("/targets/{employee_id}")
@router.get("/targets/{employee_id}/")
async def get_employee_targets(
    employee_id: str,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على أهداف موظف (للمدير أو الموظف نفسه)"""
    if employee_id != current_user.id and not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    query = db.query(EmployeeTarget).filter(EmployeeTarget.employee_id == employee_id)
    if not include_inactive:
        query = query.filter(EmployeeTarget.is_active == True)
    
    targets = query.order_by(EmployeeTarget.created_at.desc()).all()
    return targets


@router.put("/targets/{target_id}")
@router.put("/targets/{target_id}/")
async def update_target(
    target_id: str,
    update_data: EmployeeTargetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """تعديل هدف (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    target = db.query(EmployeeTarget).filter(EmployeeTarget.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="الهدف غير موجود")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(target, key, value)
    
    db.commit()
    db.refresh(target)
    
    return {"message": "تم تعديل الهدف بنجاح", "target": target}


@router.delete("/targets/{target_id}")
@router.delete("/targets/{target_id}/")
async def deactivate_target(
    target_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """إلغاء تفعيل هدف (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    target = db.query(EmployeeTarget).filter(EmployeeTarget.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="الهدف غير موجود")
    
    target.is_active = False
    db.commit()
    
    return {"message": "تم إلغاء تفعيل الهدف"}


# ======== جميع الأنشطة (للمدير) ========

@router.get("/all-activities")
@router.get("/all-activities/")
async def get_all_activities(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    role: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """جميع الأنشطة (للمدير فقط)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = EmployeePerformanceService(db)
    return service.get_all_activities(start_date, end_date, role, page, page_size)


# ======== إحصائيات سريعة ========

@router.get("/quick-stats")
@router.get("/quick-stats/")
async def get_quick_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """إحصائيات سريعة للموظف الحالي"""
    service = EmployeePerformanceService(db)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    return {
        "today": service.get_activity_count(current_user.id, today, today),
        "this_week": service.get_activity_count(current_user.id, week_start, today),
        "this_month": service.get_activity_count(current_user.id, month_start, today)
    }


# ======== تتبع الجلسات والحضور ========

from ..services.session_tracking_service import SessionTrackingService


@router.post("/heartbeat")
@router.post("/heartbeat/")
async def heartbeat(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """نبضة الحياة - تحديث حالة الاتصال"""
    service = SessionTrackingService(db)
    return service.heartbeat(current_user.id)


@router.get("/my-session")
@router.get("/my-session/")
async def get_my_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """إحصائيات جلستي اليوم"""
    service = SessionTrackingService(db)
    return service.get_my_session_stats(current_user.id)


@router.get("/employees-status")
@router.get("/employees-status/")
async def get_employees_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """حالة اتصال جميع الموظفين (للمدير)"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = SessionTrackingService(db)
    return service.get_all_employees_status()


@router.get("/attendance-report")
@router.get("/attendance-report/")
async def get_attendance_report(
    period: str = Query("weekly", description="weekly or monthly"),
    employee_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """تقرير الحضور الأسبوعي/الشهري"""
    if not current_user.is_admin_or_higher:
        raise HTTPException(status_code=403, detail="صلاحيات غير كافية")
    
    service = SessionTrackingService(db)
    return service.get_attendance_report(period, employee_id)

