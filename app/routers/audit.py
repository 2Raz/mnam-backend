"""
Audit Log Router - سجل الأنشطة
يوفر endpoints لعرض وتصفية سجل الأنشطة والسجلات المحذوفة
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from ..database import get_db
from ..models.audit_log import AuditLog, ActivityType, EntityType, ACTIVITY_LABELS, ENTITY_LABELS
from ..models.user import User
from ..models.owner import Owner
from ..models.project import Project
from ..models.unit import Unit
from ..models.booking import Booking
from ..models.customer import Customer
from ..utils.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/audit", tags=["سجل الأنشطة"])


# ============ Schemas ============

class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str]
    user_name: Optional[str]
    activity_type: str
    activity_label: str
    entity_type: str
    entity_label: str
    entity_id: Optional[str]
    entity_name: Optional[str]
    description: Optional[str]
    old_values: Optional[dict]
    new_values: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeletedRecordResponse(BaseModel):
    id: str
    entity_type: str
    entity_label: str
    name: str
    deleted_at: Optional[datetime]
    deleted_by: Optional[str]
    can_restore: bool


class DeletedRecordsListResponse(BaseModel):
    records: List[DeletedRecordResponse]
    total: int


# ============ Endpoints ============

@router.get("")
@router.get("/", response_model=AuditLogListResponse)
async def get_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    الحصول على سجل الأنشطة مع فلاتر متقدمة
    """
    query = db.query(AuditLog)
    
    # Filter by user
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    # Filter by activity type
    if activity_type:
        try:
            at = ActivityType(activity_type)
            query = query.filter(AuditLog.activity_type == at)
        except ValueError:
            pass
    
    # Filter by entity type
    if entity_type:
        try:
            et = EntityType(entity_type)
            query = query.filter(AuditLog.entity_type == et)
        except ValueError:
            pass
    
    # Filter by entity ID
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    
    # Filter by date range
    if start_date:
        try:
            start = datetime.fromisoformat(start_date)
            query = query.filter(AuditLog.created_at >= start)
        except ValueError:
            pass
    
    if end_date:
        try:
            end = datetime.fromisoformat(end_date)
            query = query.filter(AuditLog.created_at <= end)
        except ValueError:
            pass
    
    # Search in description and entity name
    if search:
        search_filter = or_(
            AuditLog.description.ilike(f"%{search}%"),
            AuditLog.entity_name.ilike(f"%{search}%"),
            AuditLog.user_name.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)
    
    # Count total
    total = query.count()
    
    # Pagination
    offset = (page - 1) * page_size
    logs = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(page_size).all()
    
    # Convert to response
    log_responses = []
    for log in logs:
        log_responses.append(AuditLogResponse(
            id=log.id,
            user_id=log.user_id,
            user_name=log.user_name,
            activity_type=log.activity_type.value,
            activity_label=ACTIVITY_LABELS.get(log.activity_type, log.activity_type.value),
            entity_type=log.entity_type.value,
            entity_label=ENTITY_LABELS.get(log.entity_type, log.entity_type.value),
            entity_id=log.entity_id,
            entity_name=log.entity_name,
            description=log.description,
            old_values=log.old_values,
            new_values=log.new_values,
            ip_address=log.ip_address,
            created_at=log.created_at
        ))
    
    total_pages = (total + page_size - 1) // page_size
    
    return AuditLogListResponse(
        logs=log_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/activity-types")
async def get_activity_types(current_user: User = Depends(get_current_user)):
    """الحصول على قائمة أنواع الأنشطة"""
    return [
        {"value": at.value, "label": ACTIVITY_LABELS.get(at, at.value)}
        for at in ActivityType
    ]


@router.get("/entity-types")
async def get_entity_types(current_user: User = Depends(get_current_user)):
    """الحصول على قائمة أنواع الكيانات"""
    return [
        {"value": et.value, "label": ENTITY_LABELS.get(et, et.value)}
        for et in EntityType
    ]


@router.get("/deleted-records", response_model=DeletedRecordsListResponse)
async def get_deleted_records(
    entity_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    الحصول على قائمة السجلات المحذوفة (soft deleted)
    """
    records = []
    
    # Collect from all entities that support soft delete
    entity_configs = [
        (Owner, EntityType.OWNER, "owner_name"),
        (Project, EntityType.PROJECT, "name"),
        (Unit, EntityType.UNIT, "unit_name"),
        (Booking, EntityType.BOOKING, "guest_name"),
        (Customer, EntityType.CUSTOMER, "name"),
        (User, EntityType.USER, "username"),
    ]
    
    for model, et, name_field in entity_configs:
        # Skip if filtering by entity type and this isn't it
        if entity_type and et.value != entity_type:
            continue
        
        # Check if model has is_deleted
        if not hasattr(model, 'is_deleted'):
            continue
        
        deleted = db.query(model).filter(model.is_deleted == True).all()
        
        for item in deleted:
            name = getattr(item, name_field, str(item.id))
            deleted_at = getattr(item, 'deleted_at', None)
            
            # Get deleted_by name
            deleted_by = None
            if hasattr(item, 'deleted_by_id') and item.deleted_by_id:
                deleter = db.query(User).filter(User.id == item.deleted_by_id).first()
                if deleter:
                    deleted_by = f"{deleter.first_name} {deleter.last_name}"
            
            records.append(DeletedRecordResponse(
                id=item.id,
                entity_type=et.value,
                entity_label=ENTITY_LABELS.get(et, et.value),
                name=name,
                deleted_at=deleted_at,
                deleted_by=deleted_by,
                can_restore=True
            ))
    
    # Sort by deleted_at desc
    records.sort(key=lambda r: r.deleted_at or datetime.min, reverse=True)
    
    return DeletedRecordsListResponse(
        records=records,
        total=len(records)
    )


@router.get("/stats")
async def get_audit_stats(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    إحصائيات سجل الأنشطة
    """
    since = datetime.utcnow() - timedelta(days=days)
    
    # Total activities
    total = db.query(AuditLog).filter(AuditLog.created_at >= since).count()
    
    # By activity type
    by_activity = {}
    for at in ActivityType:
        count = db.query(AuditLog).filter(
            AuditLog.created_at >= since,
            AuditLog.activity_type == at
        ).count()
        if count > 0:
            by_activity[at.value] = {
                "count": count,
                "label": ACTIVITY_LABELS.get(at, at.value)
            }
    
    # By entity type
    by_entity = {}
    for et in EntityType:
        count = db.query(AuditLog).filter(
            AuditLog.created_at >= since,
            AuditLog.entity_type == et
        ).count()
        if count > 0:
            by_entity[et.value] = {
                "count": count,
                "label": ENTITY_LABELS.get(et, et.value)
            }
    
    # Most active users
    from sqlalchemy import func
    active_users = db.query(
        AuditLog.user_id,
        AuditLog.user_name,
        func.count(AuditLog.id).label('count')
    ).filter(
        AuditLog.created_at >= since,
        AuditLog.user_id.isnot(None)
    ).group_by(
        AuditLog.user_id,
        AuditLog.user_name
    ).order_by(
        desc('count')
    ).limit(10).all()
    
    top_users = [
        {"user_id": u.user_id, "user_name": u.user_name, "count": u.count}
        for u in active_users
    ]
    
    # Deleted records count
    deleted_count = 0
    for model in [Owner, Project, Unit, Booking, Customer, User]:
        if hasattr(model, 'is_deleted'):
            deleted_count += db.query(model).filter(model.is_deleted == True).count()
    
    return {
        "period_days": days,
        "total_activities": total,
        "by_activity_type": by_activity,
        "by_entity_type": by_entity,
        "top_users": top_users,
        "deleted_records_count": deleted_count
    }
