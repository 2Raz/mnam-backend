"""
Pricing Policy Model

Stores pricing configurations per unit including:
- Base weekday price
- Weekend markup percentage
- Time-based intraday discounts (16:00, 21:00, 23:00)
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Numeric, ForeignKey, DateTime, Integer
from sqlalchemy.orm import relationship
from ..database import Base


class PricingPolicy(Base):
    """
    Pricing policy for a unit.
    
    Pricing Formula:
    1. base_price = base_weekday_price
    2. day_price = base_price if weekday else base_price * (1 + weekend_markup_percent/100)
    3. final_price = day_price * (1 - active_discount/100)
    
    Active discount is determined by local time:
    - Before 16:00: 0%
    - 16:00-20:59: discount_16_percent
    - 21:00-22:59: discount_21_percent
    - 23:00-23:59: discount_23_percent
    """
    __tablename__ = "pricing_policies"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    unit_id = Column(String(36), ForeignKey("units.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # Base pricing
    base_weekday_price = Column(Numeric(10, 2), nullable=False, default=100)
    currency = Column(String(3), default="SAR")
    
    # Weekend markup (percentage on top of base, e.g., 150 means price = base * 2.5)
    weekend_markup_percent = Column(Numeric(5, 2), default=0)
    
    # Intraday discounts (percentages to subtract from day price)
    discount_16_percent = Column(Numeric(5, 2), default=0)  # 16:00 - 20:59
    discount_21_percent = Column(Numeric(5, 2), default=0)  # 21:00 - 22:59
    discount_23_percent = Column(Numeric(5, 2), default=0)  # 23:00 - 23:59
    
    # Timezone for determining local time (for discount logic)
    timezone = Column(String(50), default="Asia/Riyadh")
    
    # Weekend configuration (comma-separated day numbers: 0=Mon, 4=Fri, 5=Sat, 6=Sun)
    # KSA weekend: Friday/Saturday = "4,5"
    # Western weekend: Saturday/Sunday = "5,6"
    weekend_days = Column(String(20), default="4,5")  # Default KSA weekend
    
    # Tracking
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    unit = relationship("Unit", back_populates="pricing_policy")
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    
    def get_weekend_days(self) -> set:
        """Parse weekend_days string to set of integers"""
        if not self.weekend_days:
            return {4, 5}  # Default KSA weekend
        return set(int(d.strip()) for d in self.weekend_days.split(",") if d.strip().isdigit())
    
    def __repr__(self):
        return f"<PricingPolicy unit_id={self.unit_id} base={self.base_weekday_price}>"
