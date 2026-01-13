"""Refresh Token model for multi-session support"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship
from ..database import Base


class RefreshToken(Base):
    """
    Stores refresh token hashes for secure token management.
    Supports multiple sessions per user (multi-device).
    """
    __tablename__ = "refresh_tokens"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash
    
    # Optional device/session info
    device_info = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, default=datetime.utcnow)
    
    # Revocation
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="refresh_tokens")
    
    # Indexes for performance
    __table_args__ = (
        Index('ix_refresh_tokens_user_active', 'user_id', 'is_revoked'),
    )
    
    def __repr__(self):
        return f"<RefreshToken user={self.user_id} revoked={self.is_revoked}>"
    
    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired
