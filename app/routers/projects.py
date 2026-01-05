from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models.project import Project
from ..models.owner import Owner
from ..models.unit import Unit
from ..schemas.project import ProjectResponse, ProjectCreate, ProjectUpdate, ProjectSimple
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User

router = APIRouter(prefix="/api/projects", tags=["المشاريع"])


@router.get("")
@router.get("/", response_model=List[ProjectResponse])
async def get_all_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع المشاريع"""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    
    result = []
    for project in projects:
        result.append(ProjectResponse(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            status=project.status,
            city=project.city,
            district=project.district,
            security_guard_phone=project.security_guard_phone,
            property_manager_phone=project.property_manager_phone,
            map_url=project.map_url,
            contract_no=project.contract_no,
            contract_status=project.contract_status,
            contract_duration=project.contract_duration,
            commission_percent=project.commission_percent,
            bank_name=project.bank_name,
            bank_iban=project.bank_iban,
            owner_name=project.owner.owner_name if project.owner else "غير معروف",
            unit_count=len(project.units),
            created_at=project.created_at,
            updated_at=project.updated_at
        ))
    
    return result


@router.get("/select")
@router.get("/select/", response_model=List[ProjectSimple])
async def get_projects_for_select(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة مبسطة للمشاريع (للـ Dropdown)"""
    projects = db.query(Project).all()
    return [ProjectSimple(id=p.id, name=p.name) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على بيانات مشروع محدد"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المشروع غير موجود"
        )
    
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
        status=project.status,
        city=project.city,
        district=project.district,
        security_guard_phone=project.security_guard_phone,
        property_manager_phone=project.property_manager_phone,
        map_url=project.map_url,
        contract_no=project.contract_no,
        contract_status=project.contract_status,
        contract_duration=project.contract_duration,
        commission_percent=project.commission_percent,
        bank_name=project.bank_name,
        bank_iban=project.bank_iban,
        owner_name=project.owner.owner_name if project.owner else "غير معروف",
        unit_count=len(project.units),
        created_at=project.created_at,
        updated_at=project.updated_at
    )


@router.post("")
@router.post("/", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """إضافة مشروع جديد (للمدير فقط)"""
    # Verify owner exists
    owner = db.query(Owner).filter(Owner.id == project_data.owner_id).first()
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="المالك غير موجود"
        )
    
    new_project = Project(
        owner_id=project_data.owner_id,
        name=project_data.name,
        status=project_data.status.value,
        city=project_data.city,
        district=project_data.district,
        security_guard_phone=project_data.security_guard_phone,
        property_manager_phone=project_data.property_manager_phone,
        map_url=project_data.map_url,
        contract_no=project_data.contract_no,
        contract_status=project_data.contract_status.value,
        contract_duration=project_data.contract_duration,
        commission_percent=project_data.commission_percent,
        bank_name=project_data.bank_name,
        bank_iban=project_data.bank_iban
    )
    
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    
    return ProjectResponse(
        id=new_project.id,
        owner_id=new_project.owner_id,
        name=new_project.name,
        status=new_project.status,
        city=new_project.city,
        district=new_project.district,
        security_guard_phone=new_project.security_guard_phone,
        property_manager_phone=new_project.property_manager_phone,
        map_url=new_project.map_url,
        contract_no=new_project.contract_no,
        contract_status=new_project.contract_status,
        contract_duration=new_project.contract_duration,
        commission_percent=new_project.commission_percent,
        bank_name=new_project.bank_name,
        bank_iban=new_project.bank_iban,
        owner_name=owner.owner_name,
        unit_count=0,
        created_at=new_project.created_at,
        updated_at=new_project.updated_at
    )


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """تحديث بيانات مشروع (للمدير فقط)"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المشروع غير موجود"
        )
    
    update_data = project_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field in ["status", "contract_status"] and value:
            setattr(project, field, value.value)
        else:
            setattr(project, field, value)
    
    db.commit()
    db.refresh(project)
    
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
        status=project.status,
        city=project.city,
        district=project.district,
        security_guard_phone=project.security_guard_phone,
        property_manager_phone=project.property_manager_phone,
        map_url=project.map_url,
        contract_no=project.contract_no,
        contract_status=project.contract_status,
        contract_duration=project.contract_duration,
        commission_percent=project.commission_percent,
        bank_name=project.bank_name,
        bank_iban=project.bank_iban,
        owner_name=project.owner.owner_name if project.owner else "غير معروف",
        unit_count=len(project.units),
        created_at=project.created_at,
        updated_at=project.updated_at
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """حذف مشروع (للمدير فقط)"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المشروع غير موجود"
        )
    
    db.delete(project)
    db.commit()
    
    return {"message": "تم حذف المشروع بنجاح"}
