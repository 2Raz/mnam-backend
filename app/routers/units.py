from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.unit import Unit
from ..models.project import Project
from ..schemas.unit import UnitResponse, UnitCreate, UnitUpdate, UnitSimple, UnitForSelect
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User

router = APIRouter(prefix="/api/units", tags=["الوحدات"])


@router.get("")
@router.get("/", response_model=List[UnitResponse])
async def get_all_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع الوحدات"""
    units = db.query(Unit).order_by(Unit.created_at.desc()).all()
    
    result = []
    for unit in units:
        project = unit.project
        owner_name = project.owner.owner_name if project and project.owner else "غير معروف"
        
        result.append(UnitResponse(
            id=unit.id,
            project_id=unit.project_id,
            unit_name=unit.unit_name,
            unit_type=unit.unit_type,
            rooms=unit.rooms,
            floor_number=unit.floor_number,
            unit_area=unit.unit_area,
            status=unit.status,
            price_days_of_week=unit.price_days_of_week,
            price_in_weekends=unit.price_in_weekends,
            amenities=unit.amenities or [],
            description=unit.description,
            permit_no=unit.permit_no,
            project_name=project.name if project else "غير معروف",
            owner_name=owner_name,
            city=project.city if project else None,
            created_at=unit.created_at,
            updated_at=unit.updated_at
        ))
    
    return result


@router.get("/by-project/{project_id}")
@router.get("/by-project/{project_id}/", response_model=List[UnitSimple])
async def get_units_by_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على وحدات مشروع محدد"""
    units = db.query(Unit).filter(Unit.project_id == project_id).all()
    
    return [
        UnitSimple(
            unit_name=u.unit_name,
            unit_type=u.unit_type,
            rooms=u.rooms,
            price_days_of_week=u.price_days_of_week,
            price_in_weekends=u.price_in_weekends,
            status=u.status
        )
        for u in units
    ]


@router.get("/select/{project_id}")
@router.get("/select/{project_id}/", response_model=List[UnitForSelect])
async def get_units_for_select(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة مبسطة للوحدات (للـ Dropdown)"""
    units = db.query(Unit).filter(Unit.project_id == project_id).all()
    return [
        UnitForSelect(
            id=u.id,
            unit_name=u.unit_name,
            price_days_of_week=u.price_days_of_week,
            price_in_weekends=u.price_in_weekends
        )
        for u in units
    ]


@router.get("/{unit_id}", response_model=UnitResponse)
async def get_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات وحدة محددة"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة"
        )
    
    project = unit.project
    owner_name = project.owner.owner_name if project and project.owner else "غير معروف"
    
    return UnitResponse(
        id=unit.id,
        project_id=unit.project_id,
        unit_name=unit.unit_name,
        unit_type=unit.unit_type,
        rooms=unit.rooms,
        floor_number=unit.floor_number,
        unit_area=unit.unit_area,
        status=unit.status,
        price_days_of_week=unit.price_days_of_week,
        price_in_weekends=unit.price_in_weekends,
        amenities=unit.amenities or [],
        description=unit.description,
        permit_no=unit.permit_no,
        project_name=project.name if project else "غير معروف",
        owner_name=owner_name,
        city=project.city if project else None,
        created_at=unit.created_at,
        updated_at=unit.updated_at
    )


@router.post("")
@router.post("/", response_model=UnitResponse)
async def create_unit(
    unit_data: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """إضافة وحدة جديدة (للمدير فقط)"""
    # Verify project exists
    project = db.query(Project).filter(Project.id == unit_data.project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="المشروع غير موجود"
        )
    
    new_unit = Unit(
        project_id=unit_data.project_id,
        unit_name=unit_data.unit_name,
        unit_type=unit_data.unit_type.value,
        rooms=unit_data.rooms,
        floor_number=unit_data.floor_number,
        unit_area=unit_data.unit_area,
        status=unit_data.status.value,
        price_days_of_week=unit_data.price_days_of_week,
        price_in_weekends=unit_data.price_in_weekends,
        amenities=unit_data.amenities,
        description=unit_data.description,
        permit_no=unit_data.permit_no
    )
    
    db.add(new_unit)
    db.commit()
    db.refresh(new_unit)
    
    owner_name = project.owner.owner_name if project.owner else "غير معروف"
    
    return UnitResponse(
        id=new_unit.id,
        project_id=new_unit.project_id,
        unit_name=new_unit.unit_name,
        unit_type=new_unit.unit_type,
        rooms=new_unit.rooms,
        floor_number=new_unit.floor_number,
        unit_area=new_unit.unit_area,
        status=new_unit.status,
        price_days_of_week=new_unit.price_days_of_week,
        price_in_weekends=new_unit.price_in_weekends,
        amenities=new_unit.amenities or [],
        description=new_unit.description,
        permit_no=new_unit.permit_no,
        project_name=project.name,
        owner_name=owner_name,
        city=project.city,
        created_at=new_unit.created_at,
        updated_at=new_unit.updated_at
    )


@router.put("/{unit_id}", response_model=UnitResponse)
async def update_unit(
    unit_id: str,
    unit_data: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """تحديث بيانات وحدة (للمدير فقط)"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة"
        )
    
    update_data = unit_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ["unit_type", "status"] and value:
            setattr(unit, field, value.value)
        else:
            setattr(unit, field, value)
    
    db.commit()
    db.refresh(unit)
    
    project = unit.project
    owner_name = project.owner.owner_name if project and project.owner else "غير معروف"
    
    return UnitResponse(
        id=unit.id,
        project_id=unit.project_id,
        unit_name=unit.unit_name,
        unit_type=unit.unit_type,
        rooms=unit.rooms,
        floor_number=unit.floor_number,
        unit_area=unit.unit_area,
        status=unit.status,
        price_days_of_week=unit.price_days_of_week,
        price_in_weekends=unit.price_in_weekends,
        amenities=unit.amenities or [],
        description=unit.description,
        permit_no=unit.permit_no,
        project_name=project.name if project else "غير معروف",
        owner_name=owner_name,
        city=project.city if project else None,
        created_at=unit.created_at,
        updated_at=unit.updated_at
    )


@router.delete("/{unit_id}")
async def delete_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """حذف وحدة (للمدير فقط)"""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة"
        )
    
    db.delete(unit)
    db.commit()
    
    return {"message": "تم حذف الوحدة بنجاح"}
