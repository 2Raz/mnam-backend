from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.user import User, UserRole, ASSIGNABLE_ROLES, ROLE_LABELS, get_assignable_roles
from ..schemas.user import UserResponse, UserCreate, UserUpdate, AssignableRoleResponse
from ..utils.dependencies import get_current_user, require_admin
from ..utils.security import hash_password

router = APIRouter(prefix="/api/users", tags=["المستخدمين"])


@router.get("")
@router.get("/", response_model=List[UserResponse])
async def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """الحصول على قائمة جميع المستخدمين (للمدير فقط)"""
    users = db.query(User).all()
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


@router.get("/{user_id}", response_model=UserResponse)
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
    
    return new_user


@router.put("/{user_id}", response_model=UserResponse)
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
async def delete_user(
    user_id: str,
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
    
    db.delete(user)
    db.commit()
    
    return {"message": "تم حذف المستخدم بنجاح"}
