import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from ..database import Base


class Owner(Base):
    __tablename__ = "owners"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_name = Column(String(100), nullable=False)
    owner_mobile_phone = Column(String(20), nullable=False)
    paypal_email = Column(String(100), nullable=True)
    note = Column(Text, nullable=True)
    
    # تتبع الموظفين
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Soft Delete
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Relationships
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    
    def __repr__(self):
        return f"<Owner {self.owner_name}>"

