from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal

from ..database import get_db
from ..models.unit import Unit
from ..models.project import Project
from ..models.pricing import PricingPolicy
from ..models.channel_integration import ExternalMapping
from ..schemas.unit import UnitResponse, UnitCreate, UnitUpdate, UnitSimple, UnitForSelect, ExternalMappingInfo
from ..utils.dependencies import get_current_user, require_owners_agent
from ..models.user import User
from ..services.employee_performance_service import log_unit_created, EmployeePerformanceService
from ..models.employee_performance import ActivityType
from ..models.audit_log import AuditLog, ActivityType as AuditActivityType, EntityType as AuditEntityType

router = APIRouter(prefix="/api/units", tags=["الوحدات"])


def create_or_update_pricing_policy(
    db: Session, 
    unit_id: str, 
    base_weekday_price: Decimal = None,
    weekend_markup_percent: Decimal = None,
    discount_16_percent: Decimal = None,
    discount_21_percent: Decimal = None,
    discount_23_percent: Decimal = None,
    price_days_of_week: Decimal = None,
    price_in_weekends: Decimal = None
):
    """
    إنشاء أو تحديث سياسة التسعير للوحدة
    إذا لم تُقدم base_weekday_price، يتم حسابها من price_days_of_week
    """
    # Check if pricing policy exists
    policy = db.query(PricingPolicy).filter(PricingPolicy.unit_id == unit_id).first()
    
    # Calculate base price and markup from legacy fields if new fields not provided
    if base_weekday_price is None and price_days_of_week is not None:
        base_weekday_price = price_days_of_week
    
    if weekend_markup_percent is None and price_days_of_week and price_in_weekends:
        if float(price_days_of_week) > 0 and float(price_in_weekends) > float(price_days_of_week):
            weekend_markup_percent = Decimal(
                round(((float(price_in_weekends) - float(price_days_of_week)) / float(price_days_of_week)) * 100)
            )
        else:
            weekend_markup_percent = Decimal("0")
    
    if base_weekday_price is None or float(base_weekday_price) <= 0:
        # No valid price, skip creating policy
        return None
    
    if policy:
        # Update existing policy
        policy.base_weekday_price = base_weekday_price
        if weekend_markup_percent is not None:
            policy.weekend_markup_percent = weekend_markup_percent
        if discount_16_percent is not None:
            policy.discount_16_percent = discount_16_percent
        if discount_21_percent is not None:
            policy.discount_21_percent = discount_21_percent
        if discount_23_percent is not None:
            policy.discount_23_percent = discount_23_percent
    else:
        # Create new policy
        policy = PricingPolicy(
            unit_id=unit_id,
            base_weekday_price=base_weekday_price,
            currency="SAR",
            weekend_markup_percent=weekend_markup_percent or Decimal("0"),
            discount_16_percent=discount_16_percent or Decimal("0"),
            discount_21_percent=discount_21_percent or Decimal("0"),
            discount_23_percent=discount_23_percent or Decimal("0"),
            timezone="Asia/Riyadh",
            weekend_days="4,5"  # Thursday and Friday in Python (0=Monday)
        )
        db.add(policy)
    
    return policy


def get_pricing_policy_dict(policy: PricingPolicy) -> dict:
    """Convert PricingPolicy to dict for response"""
    if not policy:
        return None
    return {
        "id": policy.id,
        "base_weekday_price": float(policy.base_weekday_price) if policy.base_weekday_price else 0,
        "weekend_markup_percent": float(policy.weekend_markup_percent) if policy.weekend_markup_percent else 0,
        "discount_16_percent": float(policy.discount_16_percent) if policy.discount_16_percent else 0,
        "discount_21_percent": float(policy.discount_21_percent) if policy.discount_21_percent else 0,
        "discount_23_percent": float(policy.discount_23_percent) if policy.discount_23_percent else 0,
        "timezone": policy.timezone,
        "currency": policy.currency,
    }


def to_unit_response(unit: Unit) -> UnitResponse:
    """
    Helper function to build UnitResponse including external_mappings.
    Prevents code duplication across all unit endpoints.
    """
    project = unit.project
    owner_name = project.owner.owner_name if project and project.owner else "غير معروف"
    
    # Build external mappings info and compute channel_status
    external_mappings = []
    has_channex = False
    channel_status = "unmapped"  # default
    has_active = False
    has_inactive = False
    has_error = False
    
    if hasattr(unit, 'external_mappings') and unit.external_mappings:
        for mapping in unit.external_mappings:
            if mapping.is_active:
                has_channex = True
                has_active = True
                # Check for sync errors
                if mapping.connection and mapping.connection.last_error:
                    has_error = True
            else:
                has_inactive = True
            
            external_mappings.append(ExternalMappingInfo(
                id=mapping.id,
                provider=mapping.connection.provider if mapping.connection else "channex",
                channex_room_type_id=mapping.channex_room_type_id,
                channex_rate_plan_id=mapping.channex_rate_plan_id,
                is_active=mapping.is_active,
                last_price_sync_at=mapping.last_price_sync_at,
                last_avail_sync_at=mapping.last_avail_sync_at
            ))
        
        # Determine channel_status priority: error > mapped > disabled > unmapped
        if has_error:
            channel_status = "error"
        elif has_active:
            channel_status = "mapped"
        elif has_inactive:
            channel_status = "disabled"
    
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
        access_info=unit.access_info,
        booking_links=unit.booking_links or [],
        project_name=project.name if project else "غير معروف",
        owner_name=owner_name,
        city=project.city if project else None,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
        pricing_policy=get_pricing_policy_dict(unit.pricing_policy),
        external_mappings=external_mappings,
        has_channex_connection=has_channex,
        channel_status=channel_status
    )


@router.get("")
@router.get("/", response_model=List[UnitResponse])
async def get_all_units(
    include_deleted: bool = Query(False, description="تضمين المحذوفين"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """الحصول على قائمة جميع الوحدات"""
    query = db.query(Unit)
    
    if not include_deleted:
        query = query.filter(Unit.is_deleted == False)
    
    units = query.order_by(Unit.created_at.desc()).all()
    return [to_unit_response(u) for u in units]


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


@router.get("/{unit_id}")
@router.get("/{unit_id}/", response_model=UnitResponse)
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
    
    return to_unit_response(unit)


@router.get("/{unit_id}/integrations")
@router.get("/{unit_id}/integrations/", response_model=List[ExternalMappingInfo])
async def get_unit_integrations(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    الحصول على ارتباطات الوحدة بالقنوات الخارجية
    
    Returns all channel mappings for a unit (Channex room types, rate plans, etc.)
    """
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة"
        )
    
    mappings = []
    if hasattr(unit, 'external_mappings') and unit.external_mappings:
        for mapping in unit.external_mappings:
            mappings.append(ExternalMappingInfo(
                id=mapping.id,
                provider=mapping.connection.provider if mapping.connection else "channex",
                channex_room_type_id=mapping.channex_room_type_id,
                channex_rate_plan_id=mapping.channex_rate_plan_id,
                is_active=mapping.is_active,
                last_price_sync_at=mapping.last_price_sync_at,
                last_avail_sync_at=mapping.last_avail_sync_at
            ))
    
    return mappings


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
        permit_no=unit_data.permit_no,
        access_info=unit_data.access_info,
        booking_links=unit_data.booking_links,
        created_by_id=current_user.id
    )
    
    db.add(new_unit)
    db.commit()
    db.refresh(new_unit)
    
    # 🆕 Create pricing policy automatically
    policy = create_or_update_pricing_policy(
        db=db,
        unit_id=new_unit.id,
        base_weekday_price=unit_data.base_weekday_price,
        weekend_markup_percent=unit_data.weekend_markup_percent,
        discount_16_percent=unit_data.discount_16_percent,
        discount_21_percent=unit_data.discount_21_percent,
        discount_23_percent=unit_data.discount_23_percent,
        price_days_of_week=unit_data.price_days_of_week,
        price_in_weekends=unit_data.price_in_weekends
    )
    if policy:
        db.commit()
    
    # تسجيل نشاط إضافة وحدة
    log_unit_created(db, current_user.id, new_unit.id)
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.CREATE,
        entity_type=AuditEntityType.UNIT,
        entity_id=new_unit.id,
        entity_name=new_unit.unit_name,
        description=f"إضافة وحدة جديدة: {new_unit.unit_name} في {project.name}",
        new_values={
            "unit_name": new_unit.unit_name,
            "unit_type": new_unit.unit_type,
            "project_name": project.name,
            "price_days_of_week": float(new_unit.price_days_of_week) if new_unit.price_days_of_week else 0
        }
    )
    
    return to_unit_response(new_unit)


@router.put("/{unit_id}")
@router.put("/{unit_id}/", response_model=UnitResponse)
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
    old_status = unit.status
    
    # Separate pricing fields
    pricing_fields = ['base_weekday_price', 'weekend_markup_percent', 
                      'discount_16_percent', 'discount_21_percent', 'discount_23_percent']
    pricing_update = {k: update_data.pop(k) for k in pricing_fields if k in update_data}
    
    for field, value in update_data.items():
        if field in ["unit_type", "status"] and value:
            setattr(unit, field, value.value)
        else:
            setattr(unit, field, value)
    
    unit.updated_by_id = current_user.id
    db.commit()
    db.refresh(unit)
    
    # 🆕 Update pricing policy
    price_changed = False
    if pricing_update or 'price_days_of_week' in update_data or 'price_in_weekends' in update_data:
        policy = create_or_update_pricing_policy(
            db=db,
            unit_id=unit.id,
            base_weekday_price=pricing_update.get('base_weekday_price'),
            weekend_markup_percent=pricing_update.get('weekend_markup_percent'),
            discount_16_percent=pricing_update.get('discount_16_percent'),
            discount_21_percent=pricing_update.get('discount_21_percent'),
            discount_23_percent=pricing_update.get('discount_23_percent'),
            price_days_of_week=unit.price_days_of_week,
            price_in_weekends=unit.price_in_weekends
        )
        if policy:
            db.commit()
            price_changed = True
    
    # 🆕 Trigger Channex sync if price changed
    if price_changed:
        try:
            from ..services.outbox_worker import enqueue_price_update
            from ..models.channel_integration import ExternalMapping, ChannelConnection, ConnectionStatus
            from sqlalchemy import and_
            
            # Find active mappings for this unit
            mappings = db.query(ExternalMapping).join(ChannelConnection).filter(
                and_(
                    ExternalMapping.unit_id == unit.id,
                    ExternalMapping.is_active == True,
                    ChannelConnection.status == ConnectionStatus.ACTIVE.value
                )
            ).all()
            
            for mapping in mappings:
                enqueue_price_update(
                    db=db,
                    unit_id=unit.id,
                    connection_id=mapping.connection_id,
                    days_ahead=365
                )
        except Exception as e:
            # Don't fail unit update if sync fails
            print(f"Warning: Failed to enqueue price sync: {e}")
    
    # تسجيل النشاط
    service = EmployeePerformanceService(db)
    if "status" in update_data and old_status != unit.status:
        # تغيير حالة الوحدة
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.UNIT_STATUS_CHANGED,
            entity_type="unit",
            entity_id=unit.id,
            description=f"تغيير حالة {unit.unit_name}: {old_status} → {unit.status}"
        )
    else:
        # تعديل عام
        service.log_activity(
            employee_id=current_user.id,
            activity_type=ActivityType.UNIT_UPDATED,
            entity_type="unit",
            entity_id=unit.id,
            description=f"تعديل وحدة: {unit.unit_name}"
        )
    
    # تسجيل في سجل الأنشطة (AuditLog)
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.UPDATE,
        entity_type=AuditEntityType.UNIT,
        entity_id=unit.id,
        entity_name=unit.unit_name,
        description=f"تحديث بيانات وحدة: {unit.unit_name}",
        old_values={"status": old_status} if old_status != unit.status else None,
        new_values=update_data
    )
    
    return to_unit_response(unit)


@router.delete("/{unit_id}")
@router.delete("/{unit_id}/")
async def delete_unit(
    unit_id: str,
    permanent: bool = Query(False, description="حذف نهائي"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """
    حذف وحدة
    - permanent=false (افتراضي): Soft Delete
    - permanent=true: حذف نهائي (للمدير فقط)
    """
    from datetime import datetime
    
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة"
        )
    
    if permanent:
        if current_user.role not in ['admin', 'system_owner']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="الحذف النهائي متاح للمدير فقط"
            )
        # حفظ اسم الوحدة قبل الحذف
        unit_name = unit.unit_name
        unit_id_temp = unit.id
        
        # تسجيل في سجل الأنشطة قبل الحذف
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.PERMANENT_DELETE,
            entity_type=AuditEntityType.UNIT,
            entity_id=unit_id_temp,
            entity_name=unit_name,
            description=f"حذف نهائي لوحدة: {unit_name}"
        )
        db.delete(unit)
        db.commit()
        return {"message": "تم حذف الوحدة نهائياً"}
    else:
        unit.is_deleted = True
        unit.deleted_at = datetime.utcnow()
        unit.deleted_by_id = current_user.id
        db.commit()
        
        # تسجيل في سجل الأنشطة
        AuditLog.log(
            db=db,
            user=current_user,
            activity_type=AuditActivityType.DELETE,
            entity_type=AuditEntityType.UNIT,
            entity_id=unit.id,
            entity_name=unit.unit_name,
            description=f"حذف وحدة: {unit.unit_name}"
        )
        return {"message": "تم حذف الوحدة بنجاح"}


@router.patch("/{unit_id}/restore")
@router.patch("/{unit_id}/restore/")
async def restore_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owners_agent)
):
    """استعادة وحدة محذوفة"""
    unit = db.query(Unit).filter(
        Unit.id == unit_id, 
        Unit.is_deleted == True
    ).first()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="الوحدة غير موجودة أو غير محذوفة"
        )
    
    unit.is_deleted = False
    unit.deleted_at = None
    unit.deleted_by_id = None
    db.commit()
    
    # تسجيل في سجل الأنشطة
    AuditLog.log(
        db=db,
        user=current_user,
        activity_type=AuditActivityType.RESTORE,
        entity_type=AuditEntityType.UNIT,
        entity_id=unit.id,
        entity_name=unit.unit_name,
        description=f"استعادة وحدة: {unit.unit_name}"
    )
    
    return {"message": "تم استعادة الوحدة بنجاح"}
