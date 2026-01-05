from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.owner import Owner
from ..models.project import Project
from ..models.unit import Unit
from ..schemas.owner import OwnerResponse, OwnerCreate, OwnerUpdate, OwnerSimple
from ..schemas.project import OwnerProjectSummary
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User

router = APIRouter(prefix="/api/owners", tags=["الملاك"])


@router.get("")
@router.get("/", response_model=List[OwnerResponse])
async def get_all_owners(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع الملاك"""
    owners = db.query(Owner).order_by(Owner.created_at.desc()).all()
    
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


@router.get("/{owner_id}", response_model=OwnerResponse)
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
        note=owner_data.note
    )
    
    db.add(new_owner)
    db.commit()
    db.refresh(new_owner)
    
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


@router.put("/{owner_id}", response_model=OwnerResponse)
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
    
    db.commit()
    db.refresh(owner)
    
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
async def delete_owner(
    owner_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """حذف مالك (للمدير فقط)"""
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المالك غير موجود"
        )
    
    db.delete(owner)
    db.commit()
    
    return {"message": "تم حذف المالك بنجاح"}
