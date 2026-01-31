from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models.user import User, UserRole, ASSIGNABLE_ROLES, ROLE_LABELS, get_assignable_roles
from ..models.task import EmployeeTask, TaskStatus
from ..schemas.user import (
    UserResponse, UserCreate, UserUpdate, AssignableRoleResponse,
    ChangePasswordRequest, UpdateMyProfileRequest, MyProfileResponse
)
from ..utils.dependencies import get_current_user, require_admin
from ..utils.security import hash_password, verify_password, validate_password_strength
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/users", tags=["المستخدمين"])


@router.get("")
@router.get("/", response_model=List[UserResponse])
async def get_all_users(
    include_deleted: bool = Query(False, description="تضمين المحذوفين"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """الحصول على قائمة جميع المستخدمين (للمدير فقط)"""
    query = db.query(User)
    
    if not include_deleted:
        query = query.filter(User.is_deleted == False)
    
    users = query.all()
    return users


@router.get("/roles/assignable")
@router.get("/roles/assignable/")
async def get_assignable_roles_endpoint(
    current_user: User = Depends(require_admin)
):
    """الحصول على قائمة الأدوار المتاحة للتعيين حسب صلاحيات المستخدم الحالي"""
    assignable = get_assignable_roles(current_user.role)
    roles = [
        {"value": role.value, "label": ROLE_LABELS.get(role, role.value)}
        for role in assignable
    ]
    return roles


@router.get("/me")
@router.get("/me/", response_model=UserResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات المستخدم الحالي"""
    return current_user


@router.get("/me/profile")
@router.get("/me/profile/")
async def get_my_full_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    الحصول على الملف الشخصي الكامل مع الإحصائيات
    """
    from datetime import date, datetime
    
    today = date.today()
    
    # عدد المهام المعلقة
    pending_tasks = db.query(EmployeeTask).filter(
        EmployeeTask.assigned_to_id == current_user.id,
        EmployeeTask.status == TaskStatus.TODO.value
    ).count()
    
    # إحصائيات اليوم من جدول الحضور
    today_activities = 0
    today_duration = 0
    try:
        from ..models.employee_session import EmployeeAttendance
        attendance = db.query(EmployeeAttendance).filter(
            EmployeeAttendance.employee_id == current_user.id,
            EmployeeAttendance.date == today
        ).first()
        if attendance:
            today_activities = attendance.activities_count
            today_duration = attendance.total_duration_minutes
    except:
        pass
    
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "phone": current_user.phone,
        "role": current_user.role,
        "role_label": ROLE_LABELS.get(UserRole(current_user.role), current_user.role),
        "is_active": current_user.is_active,
        "is_system_owner": current_user.is_system_owner,
        "last_login": current_user.last_login,
        "created_at": current_user.created_at,
        "today_activities": today_activities,
        "today_duration_minutes": today_duration,
        "pending_tasks_count": pending_tasks
    }


@router.patch("/me")
@router.patch("/me/")
async def update_my_profile(
    profile_data: UpdateMyProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    تحديث الملف الشخصي (الاسم، البريد، الجوال)
    """
    update_data = profile_data.model_dump(exclude_unset=True)
    
    # التحقق من البريد الإلكتروني إذا تم تغييره
    if "email" in update_data and update_data["email"] != current_user.email:
        existing = db.query(User).filter(
            User.email == update_data["email"],
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="البريد الإلكتروني مستخدم بالفعل"
            )
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    
    return {"message": "تم تحديث الملف الشخصي بنجاح"}


@router.patch("/me/password")
@router.patch("/me/password/")
async def change_my_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    تغيير كلمة المرور
    """
    # التحقق من كلمة المرور الحالية
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="كلمة المرور الحالية غير صحيحة"
        )
    
    # التحقق من قوة كلمة المرور الجديدة
    is_valid, error_msg = validate_password_strength(password_data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # تحديث كلمة المرور
    current_user.hashed_password = hash_password(password_data.new_password)
    db.commit()
    
    return {"message": "تم تغيير كلمة المرور بنجاح"}


@router.get("/{user_id}")
@router.get("/{user_id}/", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """الحصول على بيانات مستخدم محدد (للمدير فقط)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود"
        )
    return user


@router.post("")
@router.post("/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """إنشاء مستخدم جديد (للمدير فقط)"""
    # منع إنشاء مستخدم بدور System_Owner
    if user_data.role == UserRole.SYSTEM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن إنشاء مستخدم بدور مالك النظام"
        )
    
    # التحقق من أن المستخدم يمكنه تعيين هذا الدور
    assignable = get_assignable_roles(current_user.role)
    if user_data.role not in assignable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكنك تعيين هذا الدور"
        )
    
    # Check if username exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="اسم المستخدم مستخدم بالفعل"
        )
    
    # Check if email exists
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="البريد الإلكتروني مستخدم بالفعل"
        )
    
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        role=user_data.role.value,
        is_active=True,
        is_system_owner=False
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.USER,
        entity_id=new_user.id,
        entity_name=f"{new_user.first_name} {new_user.last_name}",
        description=f"إضافة مستخدم جديد: {new_user.username}",
        new_values={
            "username": new_user.username,
            "email": new_user.email,
            "role": new_user.role,
            "first_name": new_user.first_name,
            "last_name": new_user.last_name
        }
    )
    
    return new_user


@router.put("/{user_id}")
@router.put("/{user_id}/", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """تحديث بيانات مستخدم"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود"
        )
    
    # حماية مالك النظام من التعديل من قبل أي شخص آخر
    if user.is_system_owner and current_user.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن تعديل بيانات مالك النظام"
        )
    
    # منع تغيير دور مالك النظام
    if user.is_system_owner and user_data.role and user_data.role != UserRole.SYSTEM_OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن تغيير دور مالك النظام"
        )
    
    # منع ترقية أي شخص إلى System_Owner
    if user_data.role == UserRole.SYSTEM_OWNER and not user.is_system_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن ترقية مستخدم إلى دور مالك النظام"
        )
    
    # التحقق من صلاحية التعديل
    if current_user.id != user_id:
        if not current_user.can_modify_user(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="غير مصرح لك بتعديل هذا المستخدم"
            )
    
    # التحقق من صلاحية تغيير الدور
    if user_data.role and user_data.role.value != user.role:
        assignable = get_assignable_roles(current_user.role)
        if user_data.role not in assignable:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="لا يمكنك تعيين هذا الدور"
            )
    
    # Update fields if provided
    update_data = user_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        if field == "role" and value:
            setattr(user, field, value.value)
        else:
            setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.USER,
        entity_id=user.id,
        entity_name=f"{user.first_name} {user.last_name}",
        description=f"تحديث بيانات مستخدم: {user.username}",
        new_values=update_data
    )
    
    return user


@router.patch("/{user_id}/toggle-active")
@router.patch("/{user_id}/toggle-active/")
async def toggle_user_active(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """تفعيل/تعطيل مستخدم"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود"
        )
    
    # حماية مالك النظام من التعطيل
    if user.is_system_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="لا يمكن تعطيل مالك النظام"
        )
    
    # التحقق من صلاحية التعديل
    if not current_user.can_modify_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح لك بتعديل هذا المستخدم"
        )
    
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    
    return {"message": f"تم {'تفعيل' if user.is_active else 'تعطيل'} المستخدم بنجاح", "is_active": user.is_active}


@router.delete("/{user_id}")
@router.delete("/{user_id}/")
async def delete_user(
    user_id: str,
    permanent: bool = Query(False, description="حذف نهائي"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """حذف مستخدم (للمدير فقط)"""
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="لا يمكنك حذف حسابك الخاص"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود"
        )
    
    # حماية مالك النظام من الحذف
    if user.is_system_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="🔒 لا يمكن حذف مالك النظام - هذا المستخدم محمي"
        )
    
    # التحقق من صلاحية الحذف
    if not current_user.can_modify_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="غير مصرح لك بحذف هذا المستخدم"
        )
    
    if permanent:
        if current_user.role not in ['admin', 'system_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحذف النهائي متاح للمدير فقط"
            )
        # حفظ بيانات المستخدم قبل الحذف
        user_name = f"{user.first_name} {user.last_name}"
        user_id_temp = user.id
        
        # تسجيل في سجل الأنشطة قبل الحذف
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.PERMANENT_DELETE,
            entity_type=AuditEntityType.USER,
            entity_id=user_id_temp,
            entity_name=user_name,
            description=f"حذف نهائي لمستخدم: {user.username}"
        )
        db.delete(user)
        db.commit()
        return {"message": "تم حذف المستخدم نهائياً"}
    else:
        from datetime import datetime
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        user.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.USER,
            entity_id=user.id,
            entity_name=f"{user.first_name} {user.last_name}",
            description=f"حذف مستخدم: {user.username}"
        )
        return {"message": "تم حذف المستخدم بنجاح"}


@router.patch("/{user_id}/restore")
@router.patch("/{user_id}/restore/")
async def restore_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """استعادة مستخدم محذوف"""
    user = db.query(User).filter(
        User.id == user_id, 
        User.is_deleted == True
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المستخدم غير موجود أو غير محذوف"
        )
    
    user.is_deleted = False
    user.deleted_at = None
    user.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.USER,
        entity_id=user.id,
        entity_name=f"{user.first_name} {user.last_name}",
        description=f"استعادة مستخدم: {user.username}"
    )
    
    return {"message": "تم استعادة المستخدم بنجاح"}
