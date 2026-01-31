"""
Router للبحث العام - Global Search Router
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pydantic import BaseModel

from ..database import get_db
from ..utils.dependencies import get_current_user
from ..models import User, Booking, Unit, Customer, Owner, Project


router = APIRouter(prefix="/api/search", tags=["Search"])


# ============ Schemas ============

class SearchResultItem(BaseModel):
    id: str
    type: str  # booking, unit, customer, owner, project
    title: str
    subtitle: Optional[str] = None
    icon: str
    url: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    total: int
    results: List[SearchResultItem]
    categories: dict


# ============ Endpoints ============

@router.get("", response_model=SearchResponse)
@router.get("/", response_model=SearchResponse)
async def global_search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, le=50, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    البحث الشامل في جميع الكيانات
    
    يبحث في:
    - الحجوزات (اسم الضيف، رقم الجوال)
    - الوحدات (اسم الوحدة)
    - العملاء (الاسم، رقم الجوال)
    - الملاك (الاسم، رقم الجوال)
    - المشاريع (اسم المشروع)
    """
    results = []
    categories = {
        "bookings": 0,
        "units": 0,
        "customers": 0,
        "owners": 0,
        "projects": 0
    }
    
    search_pattern = f"%{q}%"
    
    # 1. البحث في الحجوزات
    bookings = db.query(Booking).filter(
        Booking.is_deleted == False,
        or_(
            Booking.guest_name.ilike(search_pattern),
            Booking.guest_phone.ilike(search_pattern),
            Booking.guest_email.ilike(search_pattern)
        )
    ).limit(limit // 5 + 2).all()
    
    for b in bookings:
        results.append(SearchResultItem(
            id=b.id,
            type="booking",
            title=b.guest_name,
            subtitle=f"{b.check_in_date} - {b.status}",
            icon="📅",
            url=f"/bookings/{b.id}"
        ))
        categories["bookings"] += 1
    
    # 2. البحث في الوحدات
    units = db.query(Unit).filter(
        Unit.is_deleted == False,
        or_(
            Unit.unit_name.ilike(search_pattern),
            Unit.description.ilike(search_pattern)
        )
    ).limit(limit // 5 + 2).all()
    
    for u in units:
        results.append(SearchResultItem(
            id=u.id,
            type="unit",
            title=u.unit_name,
            subtitle=f"{u.unit_type} - {u.status}",
            icon="🏠",
            url=f"/units/{u.id}"
        ))
        categories["units"] += 1
    
    # 3. البحث في العملاء
    customers = db.query(Customer).filter(
        Customer.is_deleted == False,
        or_(
            Customer.name.ilike(search_pattern),
            Customer.phone.ilike(search_pattern),
            Customer.email.ilike(search_pattern)
        )
    ).limit(limit // 5 + 2).all()
    
    for c in customers:
        results.append(SearchResultItem(
            id=c.id,
            type="customer",
            title=c.name,
            subtitle=f"{c.phone} - {c.booking_count} حجز",
            icon="👤",
            url=f"/customers/{c.id}"
        ))
        categories["customers"] += 1
    
    # 4. البحث في الملاك
    owners = db.query(Owner).filter(
        Owner.is_deleted == False,
        or_(
            Owner.owner_name.ilike(search_pattern),
            Owner.owner_mobile_phone.ilike(search_pattern)
        )
    ).limit(limit // 5 + 2).all()
    
    for o in owners:
        results.append(SearchResultItem(
            id=o.id,
            type="owner",
            title=o.owner_name,
            subtitle=f"{o.owner_mobile_phone}",
            icon="👔",
            url=f"/owners/{o.id}"
        ))
        categories["owners"] += 1
    
    # 5. البحث في المشاريع
    projects = db.query(Project).filter(
        Project.is_deleted == False,
        or_(
            Project.name.ilike(search_pattern),
            Project.city.ilike(search_pattern),
            Project.district.ilike(search_pattern)
        )
    ).limit(limit // 5 + 2).all()
    
    for p in projects:
        results.append(SearchResultItem(
            id=p.id,
            type="project",
            title=p.name,
            subtitle=f"{p.city or ''} - {p.district or ''}".strip(' - '),
            icon="🏗️",
            url=f"/projects/{p.id}"
        ))
        categories["projects"] += 1
    
    # ترتيب النتائج حسب الأهمية (الأحدث أولاً)
    results = results[:limit]
    
    return SearchResponse(
        query=q,
        total=len(results),
        results=results,
        categories=categories
    )
