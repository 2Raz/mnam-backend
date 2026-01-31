from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models.project import Project
from ..models.owner import Owner
from ..models.unit import Unit
from ..schemas.project import ProjectResponse, ProjectCreate, ProjectUpdate, ProjectSimple
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User
from ..services.employee_performance_service import log_project_created, EmployeePerformanceService
from ..models.employee_performance import ActivityType
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/projects", tags=["المشاريع"])


@router.get("")
@router.get("/", response_model=List[ProjectResponse])
async def get_all_projects(
    include_deleted: bool = Query(False, description="تضمين المحذوفين"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع المشاريع"""
    query = db.query(Project)
    
    if not include_deleted:
        query = query.filter(Project.is_deleted == False)
    
    projects = query.order_by(Project.created_at.desc()).all()
    
    result = []
    for project in projects:
        result.append(ProjectResponse(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
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


@router.get("/{project_id}")
@router.get("/{project_id}/", response_model=ProjectResponse)
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
        bank_iban=project_data.bank_iban,
        created_by_id=current_user.id
    )
    
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    
    # تسجيل نشاط إنشاء مشروع
    log_project_created(db, current_user.id, new_project.id)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.PROJECT,
        entity_id=new_project.id,
        entity_name=new_project.name,
        description=f"إنشاء مشروع جديد: {new_project.name}",
        new_values={
            "name": new_project.name,
            "city": new_project.city,
            "district": new_project.district,
            "owner_name": owner.owner_name
        }
    )
    
    return ProjectResponse(
        id=new_project.id,
        owner_id=new_project.owner_id,
        name=new_project.name,
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


@router.put("/{project_id}")
@router.put("/{project_id}/", response_model=ProjectResponse)
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
        if field == "contract_status" and value:
            setattr(project, field, value.value)
        else:
            setattr(project, field, value)
    
    project.updated_by_id = current_user.id
    db.commit()
    db.refresh(project)
    
    # تسجيل نشاط تعديل مشروع
    service = EmployeePerformanceService(db)
    service.log_activity(
        employee_id=current_user.id,
        activity_type=ActivityType.PROJECT_UPDATED,
        entity_type="project",
        entity_id=project.id,
        description=f"تعديل مشروع: {project.name}"
    )
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.PROJECT,
        entity_id=project.id,
        entity_name=project.name,
        description=f"تحديث بيانات مشروع: {project.name}",
        new_values=update_data
    )
    
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
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
@router.delete("/{project_id}/")
async def delete_project(
    project_id: str,
    permanent: bool = Query(False, description="حذف نهائي"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """
    حذف مشروع
    - permanent=false (افتراضي): Soft Delete
    - permanent=true: حذف نهائي (للمدير فقط)
    """
    from datetime import datetime
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المشروع غير موجود"
        )
    
    if permanent:
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
            entity_type=AuditEntityType.PROJECT,
            entity_id=project.id,
            entity_name=project.name,
            description=f"حذف نهائي لمشروع: {project.name}"
        )
        db.delete(project)
        db.commit()
        return {"message": "تم حذف المشروع نهائياً"}
    else:
        project.is_deleted = True
        project.deleted_at = datetime.utcnow()
        project.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.PROJECT,
            entity_id=project.id,
            entity_name=project.name,
            description=f"حذف مشروع: {project.name}"
        )
        return {"message": "تم حذف المشروع بنجاح"}


@router.patch("/{project_id}/restore")
@router.patch("/{project_id}/restore/")
async def restore_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """استعادة مشروع محذوف"""
    project = db.query(Project).filter(
        Project.id == project_id, 
        Project.is_deleted == True
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="المشروع غير موجود أو غير محذوف"
        )
    
    project.is_deleted = False
    project.deleted_at = None
    project.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.PROJECT,
        entity_id=project.id,
        entity_name=project.name,
        description=f"استعادة مشروع: {project.name}"
    )
    
    return {"message": "تم استعادة المشروع بنجاح"}
