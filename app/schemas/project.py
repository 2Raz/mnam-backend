from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class ContractStatus(str, Enum):
    ACTIVE = "ساري"
    EXPIRED = "منتهي"
    SUSPENDED = "موقف مؤقتاً"


class ProjectBase(BaseModel):
    owner_id: Optional[str]
    name: str
    city: Optional[str] = None
    district: Optional[str] = None
    security_guard_phone: Optional[str] = None
    property_manager_phone: Optional[str] = None
    map_url: Optional[str] = None
    # حقول العقد
    contract_no: Optional[str] = None
    contract_status: ContractStatus = ContractStatus.ACTIVE
    contract_duration: Optional[int] = None
    commission_percent: Decimal = Decimal("0")
    bank_name: Optional[str] = None
    bank_iban: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    owner_id: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    security_guard_phone: Optional[str] = None
    property_manager_phone: Optional[str] = None
    map_url: Optional[str] = None
    # حقول العقد
    contract_no: Optional[str] = None
    contract_status: Optional[ContractStatus] = None
    contract_duration: Optional[str] = None
    commission_percent: Optional[Decimal] = None
    bank_name: Optional[str] = None
    bank_iban: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: str
    owner_name: str = ""
    unit_count: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProjectSimple(BaseModel):
    id: str
    name: str
    
    class Config:
        from_attributes = True


class OwnerProjectSummary(BaseModel):
    project_name: str
    city: str = ""
    district: str = ""
    unit_count: int = 0
