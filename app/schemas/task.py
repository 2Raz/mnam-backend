"""
Schemas للمهام
Task Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from enum import Enum


class TaskStatus(str, Enum):
    TODO = "todo"
    DONE = "done"


class TaskCreate(BaseModel):
    """إنشاء مهمة جديدة"""
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: Optional[date] = None
    assigned_to_id: str


class TaskUpdate(BaseModel):
    """تحديث مهمة"""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[TaskStatus] = None


class TaskResponse(BaseModel):
    """استجابة المهمة"""
    id: str
    title: str
    description: Optional[str]
    due_date: Optional[date]
    status: str
    assigned_to_id: str
    created_by_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Optional: assigned user info
    assigned_to_name: Optional[str] = None
    created_by_name: Optional[str] = None
    
    class Config:
        from_attributes = True
