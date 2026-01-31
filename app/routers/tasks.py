"""
API للمهام + حساب الحجوزات اليومية للموظفين
Tasks API + Daily Bookings Count
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, cast, Date
from typing import Optional, List
from datetime import date, datetime, timedelta
import pytz

from ..database import get_db
from ..models.user import User
from ..models.task import EmployeeTask, TaskStatus
from ..models.booking import Booking, BookingStatus
from ..schemas.task import TaskCreate, TaskUpdate, TaskResponse
from ..utils.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


# ======== Helper: Timezone-aware Today ========
def get_today_riyadh() -> date:
    """Get today's date in Asia/Riyadh timezone"""
    riyadh_tz = pytz.timezone("Asia/Riyadh")
    return datetime.now(riyadh_tz).date()


def get_today_start_utc() -> datetime:
    """Get start of today (Asia/Riyadh) in UTC"""
    riyadh_tz = pytz.timezone("Asia/Riyadh")
    today_riyadh = datetime.now(riyadh_tz).date()
    start_of_day = riyadh_tz.localize(datetime.combine(today_riyadh, datetime.min.time()))
    return start_of_day.astimezone(pytz.UTC).replace(tzinfo=None)


def get_today_end_utc() -> datetime:
    """Get end of today (Asia/Riyadh) in UTC"""
    riyadh_tz = pytz.timezone("Asia/Riyadh")
    today_riyadh = datetime.now(riyadh_tz).date()
    end_of_day = riyadh_tz.localize(datetime.combine(today_riyadh, datetime.max.time()))
    return end_of_day.astimezone(pytz.UTC).replace(tzinfo=None)


# ======== حساب الحجوزات اليومية مباشرة من Booking table ========
def count_bookings_today(db: Session, employee_id: str) -> int:
    """
    عدد الحجوزات التي أنشأها الموظف اليوم (Asia/Riyadh timezone)
    الشرط: created_by_id == employee_id AND created_at is today AND status != 'ملغي'
    """
    start_utc = get_today_start_utc()
    end_utc = get_today_end_utc()
    
    count = db.query(func.count(Booking.id)).filter(
        Booking.created_by_id == employee_id,
        Booking.created_at >= start_utc,
        Booking.created_at <= end_utc,
        Booking.status != BookingStatus.CANCELLED.value
    ).scalar()
    
    return count or 0


# ======== Tasks CRUD ========

@router.get("")
@router.get("/")
def get_tasks(
    assigned_to_id: Optional[str] = Query(None, description="Filter by assignee"),
    status: Optional[str] = Query(None, description="Filter by status (todo/done)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على قائمة المهام"""
    query = db.query(EmployeeTask)
    
    # Filter by assignee
    if assigned_to_id:
        query = query.filter(EmployeeTask.assigned_to_id == assigned_to_id)
    
    # Filter by status
    if status:
        query = query.filter(EmployeeTask.status == status)
    
    total = query.count()
    tasks = query.order_by(EmployeeTask.created_at.desc())\
        .offset((page - 1) * page_size)\
        .limit(page_size)\
        .all()
    
    # Build response with user names
    result = []
    for task in tasks:
        task_dict = {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "due_date": task.due_date,
            "status": task.status,
            "assigned_to_id": task.assigned_to_id,
            "created_by_id": task.created_by_id,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "assigned_to_name": f"{task.assigned_to.first_name} {task.assigned_to.last_name}" if task.assigned_to else None,
            "created_by_name": f"{task.created_by.first_name} {task.created_by.last_name}" if task.created_by else None
        }
        result.append(task_dict)
    
    return {
        "tasks": result,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/my")
@router.get("/my/")
def get_my_tasks(
    status: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """الحصول على مهامي"""
    query = db.query(EmployeeTask).filter(
        EmployeeTask.assigned_to_id == current_user.id
    )
    
    if status:
        query = query.filter(EmployeeTask.status == status)
    
    tasks = query.order_by(
        EmployeeTask.status.asc(),  # todo first
        EmployeeTask.due_date.asc().nullslast(),  # by due date
        EmployeeTask.created_at.desc()
    ).all()
    
    result = []
    for task in tasks:
        result.append({
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "due_date": task.due_date,
            "status": task.status,
            "assigned_to_id": task.assigned_to_id,
            "created_by_id": task.created_by_id,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "assigned_to_name": None,
            "created_by_name": f"{task.created_by.first_name} {task.created_by.last_name}" if task.created_by else None
        })
    
    return {"tasks": result, "total": len(result)}


@router.post("")
@router.post("/")
def create_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """إنشاء مهمة جديدة"""
    # Verify assignee exists
    assignee = db.query(User).filter(User.id == task_data.assigned_to_id).first()
    if not assignee:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    
    task = EmployeeTask(
        title=task_data.title,
        description=task_data.description,
        due_date=task_data.due_date,
        assigned_to_id=task_data.assigned_to_id,
        created_by_id=current_user.id,
        status=TaskStatus.TODO.value
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date,
        "status": task.status,
        "assigned_to_id": task.assigned_to_id,
        "created_by_id": task.created_by_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "assigned_to_name": f"{assignee.first_name} {assignee.last_name}",
        "created_by_name": f"{current_user.first_name} {current_user.last_name}"
    }


@router.put("/{task_id}")
@router.put("/{task_id}/")
def update_task(
    task_id: str,
    task_data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """تحديث مهمة"""
    task = db.query(EmployeeTask).filter(EmployeeTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    
    # Update fields
    update_dict = task_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        if field == "status" and value:
            setattr(task, field, value.value)
        else:
            setattr(task, field, value)
    
    db.commit()
    db.refresh(task)
    
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_date": task.due_date,
        "status": task.status,
        "assigned_to_id": task.assigned_to_id,
        "created_by_id": task.created_by_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at
    }


@router.patch("/{task_id}/toggle")
@router.patch("/{task_id}/toggle/")
def toggle_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """تبديل حالة المهمة (todo <-> done)"""
    task = db.query(EmployeeTask).filter(EmployeeTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    
    # Toggle status
    new_status = TaskStatus.DONE.value if task.status == TaskStatus.TODO.value else TaskStatus.TODO.value
    task.status = new_status
    
    db.commit()
    db.refresh(task)
    
    return {"id": task.id, "status": task.status, "message": "تم تحديث حالة المهمة"}


@router.delete("/{task_id}")
@router.delete("/{task_id}/")
def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """حذف مهمة"""
    task = db.query(EmployeeTask).filter(EmployeeTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    
    db.delete(task)
    db.commit()
    
    return {"message": "تم حذف المهمة بنجاح"}


# ======== Employee Profile Endpoint ========

@router.get("/employee/{employee_id}/profile")
@router.get("/employee/{employee_id}/profile/")
def get_employee_profile(
    employee_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    الحصول على ملف الموظف الشامل:
    - البيانات الأساسية
    - حجوزات اليوم (محسوبة صح من Booking table)
    - الهدف اليومي
    - نسبة الإنجاز
    - المهام
    """
    employee = db.query(User).filter(User.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="الموظف غير موجود")
    
    # حساب الحجوزات اليومية بالطريقة الصحيحة
    booked_today_count = count_bookings_today(db, employee_id)
    
    # الهدف اليومي من EmployeeTarget
    from ..models.employee_performance import EmployeeTarget
    today = get_today_riyadh()
    current_target = db.query(EmployeeTarget).filter(
        EmployeeTarget.employee_id == employee_id,
        EmployeeTarget.is_active == True,
        EmployeeTarget.start_date <= today,
        EmployeeTarget.end_date >= today
    ).first()
    
    daily_target = current_target.target_bookings if current_target else 0
    
    # نسبة الإنجاز
    progress_percent = 0.0
    if daily_target > 0:
        progress_percent = min((booked_today_count / daily_target) * 100, 100.0)
    
    # المهام
    tasks = db.query(EmployeeTask).filter(
        EmployeeTask.assigned_to_id == employee_id
    ).order_by(
        EmployeeTask.status.asc(),
        EmployeeTask.due_date.asc().nullslast()
    ).limit(20).all()
    
    tasks_list = []
    for t in tasks:
        tasks_list.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "due_date": t.due_date,
            "status": t.status,
            "created_at": t.created_at
        })
    
    # إحصائيات المهام
    todo_count = db.query(func.count(EmployeeTask.id)).filter(
        EmployeeTask.assigned_to_id == employee_id,
        EmployeeTask.status == TaskStatus.TODO.value
    ).scalar() or 0
    
    done_count = db.query(func.count(EmployeeTask.id)).filter(
        EmployeeTask.assigned_to_id == employee_id,
        EmployeeTask.status == TaskStatus.DONE.value
    ).scalar() or 0
    
    return {
        "employee": {
            "id": employee.id,
            "username": employee.username,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "email": employee.email,
            "phone": employee.phone,
            "role": employee.role,
            "is_active": employee.is_active,
            "last_login": employee.last_login
        },
        "daily_performance": {
            "booked_today_count": booked_today_count,
            "daily_target": daily_target,
            "progress_percent": round(progress_percent, 1),
            "date": str(get_today_riyadh())
        },
        "tasks": {
            "items": tasks_list,
            "todo_count": todo_count,
            "done_count": done_count,
            "total": todo_count + done_count
        }
    }
