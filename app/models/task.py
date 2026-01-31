"""
نظام المهام للموظفين
Employee Tasks System
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Date, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum
from ..database import Base


class TaskStatus(str, enum.Enum):
    """حالة المهمة"""
    TODO = "todo"
    DONE = "done"


class EmployeeTask(Base):
    """
    مهام الموظفين
    Tasks assigned to employees
    """
    __tablename__ = "employee_tasks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(20), default=TaskStatus.TODO.value)
    
    # الموظف المكلف بالمهمة
    assigned_to_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # من أنشأ المهمة
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    
    def __repr__(self):
        return f"<Task {self.title} - {self.status}>"
