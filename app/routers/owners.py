from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models.owner import Owner
from ..models.project import Project
from ..models.unit import Unit
from ..schemas.owner import OwnerResponse, OwnerCreate, OwnerUpdate, OwnerSimple
from ..schemas.project import OwnerProjectSummary
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User
from ..services.employee_performance_service import log_owner_created, EmployeePerformanceService
from ..models.employee_performance import ActivityType
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/owners", tags=["الملاك"])


@router.get("")
@router.get("/", response_model=List[OwnerResponse])
async def get_all_owners(
    include_deleted: bool = Query(False, description="تضمين المحذوفين"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع الملاك"""
    query = db.query(Owner)
    
    if not include_deleted:
        query = query.filter(Owner.is_deleted == False)
    
    owners = query.order_by(Owner.created_at.desc()).all()
    
    # Add project and unit counts
    result = []
    for owner in owners:
        owner_dict = {
            "id": owner.id,
            "owner_name": owner.owner_name,
            "owner_mobile_phone": owner.owner_mobile_phone,
            "paypal_email": owner.paypal_email,
            "note": owner.note,
            "created_at": owner.created_at,
            "updated_at": owner.updated_at,
            "project_count": len(owner.projects),
            "unit_count": sum(len(p.units) for p in owner.projects)
        }
        result.append(OwnerResponse(**owner_dict))
    
    return result


@router.get("/select")
@router.get("/select/", response_model=List[OwnerSimple])
async def get_owners_for_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة مبسطة للملاك (للـ Dropdown)"""
    owners = db.query(Owner).all()
    return [OwnerSimple(id=o.id, name=o.owner_name) for o in owners]


@router.get("/{owner_id}")
@router.get("/{owner_id}/", response_model=OwnerResponse)
async def get_owner(
    owner_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات مالك محدد"""
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود"
        )
    
    return OwnerResponse(
        id=owner.id,
        owner_name=owner.owner_name,
        owner_mobile_phone=owner.owner_mobile_phone,
        paypal_email=owner.paypal_email,
        note=owner.note,
        created_at=owner.created_at,
        updated_at=owner.updated_at,
        project_count=len(owner.projects),
        unit_count=sum(len(p.units) for p in owner.projects)
    )


@router.get("/{owner_id}/projects")
@router.get("/{owner_id}/projects/", response_model=List[OwnerProjectSummary])
async def get_owner_projects(
    owner_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على مشاريع مالك محدد"""
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود"
        )
    
    return [
        OwnerProjectSummary(
            project_name=p.name,
            city=p.city or "",
            district=p.district or "",
            unit_count=len(p.units)
        )
        for p in owner.projects
    ]


@router.post("")
@router.post("/", response_model=OwnerResponse)
async def create_owner(
    owner_data: OwnerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """إضافة مالك جديد (للمدير فقط)"""
    new_owner = Owner(
        owner_name=owner_data.owner_name,
        owner_mobile_phone=owner_data.owner_mobile_phone,
        paypal_email=owner_data.paypal_email,
        note=owner_data.note,
        created_by_id=current_user.id
    )
    
    db.add(new_owner)
    db.commit()
    db.refresh(new_owner)
    
    # تسجيل نشاط إضافة مالك
    log_owner_created(db, current_user.id, new_owner.id)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.OWNER,
        entity_id=new_owner.id,
        entity_name=new_owner.owner_name,
        description=f"إضافة مالك جديد: {new_owner.owner_name}",
        new_values={
            "owner_name": new_owner.owner_name,
            "owner_mobile_phone": new_owner.owner_mobile_phone,
            "paypal_email": new_owner.paypal_email
        }
    )
    
    return OwnerResponse(
        id=new_owner.id,
        owner_name=new_owner.owner_name,
        owner_mobile_phone=new_owner.owner_mobile_phone,
        paypal_email=new_owner.paypal_email,
        note=new_owner.note,
        created_at=new_owner.created_at,
        updated_at=new_owner.updated_at,
        project_count=0,
        unit_count=0
    )


@router.put("/{owner_id}")
@router.put("/{owner_id}/", response_model=OwnerResponse)
async def update_owner(
    owner_id: str,
    owner_data: OwnerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """تحديث بيانات مالك (للمدير فقط)"""
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود"
        )
    
    update_data = owner_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(owner, field, value)
    
    owner.updated_by_id = current_user.id
    db.commit()
    db.refresh(owner)
    
    # تسجيل نشاط تعديل مالك
    service = EmployeePerformanceService(db)
    service.log_activity(
        employee_id=current_user.id,
        activity_type=ActivityType.OWNER_UPDATED,
        entity_type="owner",
        entity_id=owner.id,
        description=f"تعديل مالك: {owner.owner_name}"
    )
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.OWNER,
        entity_id=owner.id,
        entity_name=owner.owner_name,
        description=f"تحديث بيانات مالك: {owner.owner_name}",
        new_values=update_data
    )
    
    return OwnerResponse(
        id=owner.id,
        owner_name=owner.owner_name,
        owner_mobile_phone=owner.owner_mobile_phone,
        paypal_email=owner.paypal_email,
        note=owner.note,
        created_at=owner.created_at,
        updated_at=owner.updated_at,
        project_count=len(owner.projects),
        unit_count=sum(len(p.units) for p in owner.projects)
    )


@router.delete("/{owner_id}")
@router.delete("/{owner_id}/")
async def delete_owner(
    owner_id: str,
    permanent: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """
    حذف مالك
    - permanent=false (افتراضي): Soft Delete - يتم إخفاءه فقط
    - permanent=true: حذف نهائي (للمدير فقط)
    """
    from datetime import datetime
    
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود"
        )
    
    if permanent:
        # حذف نهائي - للمدير فقط
        if current_user.role not in ['admin', 'system_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحذف النهائي متاح للمدير فقط"
            )
        # تسجيل في سجل الأنشطة قبل الحذف
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.PERMANENT_DELETE,
            entity_type=AuditEntityType.OWNER,
            entity_id=owner.id,
            entity_name=owner.owner_name,
            description=f"حذف نهائي لمالك: {owner.owner_name}"
        )
        db.delete(owner)
        db.commit()
        return {"message": "تم حذف المالك نهائياً"}
    else:
        # Soft Delete
        owner.is_deleted = True
        owner.deleted_at = datetime.utcnow()
        owner.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.OWNER,
            entity_id=owner.id,
            entity_name=owner.owner_name,
            description=f"حذف مالك: {owner.owner_name}"
        )
        return {"message": "تم حذف المالك بنجاح"}


@router.patch("/{owner_id}/restore")
@router.patch("/{owner_id}/restore/")
async def restore_owner(
    owner_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """استعادة مالك محذوف"""
    owner = db.query(Owner).filter(Owner.id == owner_id, Owner.is_deleted == True).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود أو غير محذوف"
        )
    
    owner.is_deleted = False
    owner.deleted_at = None
    owner.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.OWNER,
        entity_id=owner.id,
        entity_name=owner.owner_name,
        description=f"استعادة مالك: {owner.owner_name}"
    )
    
    return {"message": "تم استعادة المالك بنجاح"}
