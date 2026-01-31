"""
Rate State Model

Stores per-property rate limiting state and pause status.
Supports token bucket algorithm for Channex rate limits:
- 10 price+restrictions requests/min per property
- 10 availability requests/min per property

On 429: pause property for 60s, then exponential backoff.
"""

import uuid
from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, Integer, Float
from ..database import Base


class PropertyRateState(Base):
    """
    Tracks rate limiting state per Channex property.
    
    Token bucket algorithm:
    - tokens: current available tokens (starts at max)
    - last_refill_at: when tokens were last refilled
    - Refill rate: 10 tokens per minute
    
    Pause state:
    - paused_until: if set and > now, property is paused
    - pause_count: how many consecutive pauses (for exponential backoff)
    """
    __tablename__ = "property_rate_states"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # The Channex property ID (NOT internal project_id)
    channex_property_id = Column(String(100), unique=True, nullable=False)
    
    # Token bucket for PRICE requests
    price_tokens = Column(Float, default=10.0)
    price_last_refill_at = Column(DateTime, default=datetime.utcnow)
    
    # Token bucket for AVAILABILITY requests
    avail_tokens = Column(Float, default=10.0)
    avail_last_refill_at = Column(DateTime, default=datetime.utcnow)
    
    # Pause state (on 429)
    paused_until = Column(DateTime, nullable=True)
    pause_count = Column(Integer, default=0)
    last_429_at = Column(DateTime, nullable=True)
    
    # Stats
    total_requests = Column(Integer, default=0)
    total_429s = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Constants
    MAX_TOKENS = 10.0
    REFILL_RATE = 10.0 / 60.0  # 10 tokens per minute = 1/6 token per second
    BASE_PAUSE_SECONDS = 60
    MAX_PAUSE_SECONDS = 600  # 10 minutes max pause
    
    def refill_tokens(self, bucket: str = "price") -> float:
        """
        Refill tokens based on time elapsed since last refill.
        Returns current token count after refill.
        """
        now = datetime.utcnow()
        
        if bucket == "price":
            last_refill = self.price_last_refill_at or now
            elapsed_seconds = (now - last_refill).total_seconds()
            refill_amount = elapsed_seconds * self.REFILL_RATE
            self.price_tokens = min(self.MAX_TOKENS, self.price_tokens + refill_amount)
            self.price_last_refill_at = now
            return self.price_tokens
        else:  # availability
            last_refill = self.avail_last_refill_at or now
            elapsed_seconds = (now - last_refill).total_seconds()
            refill_amount = elapsed_seconds * self.REFILL_RATE
            self.avail_tokens = min(self.MAX_TOKENS, self.avail_tokens + refill_amount)
            self.avail_last_refill_at = now
            return self.avail_tokens
    
    def consume_token(self, bucket: str = "price") -> bool:
        """
        Try to consume a token. Returns True if successful, False if no tokens.
        """
        self.refill_tokens(bucket)
        
        if bucket == "price":
            if self.price_tokens >= 1.0:
                self.price_tokens -= 1.0
                self.total_requests += 1
                return True
            return False
        else:
            if self.avail_tokens >= 1.0:
                self.avail_tokens -= 1.0
                self.total_requests += 1
                return True
            return False
    
    def wait_time_for_token(self, bucket: str = "price") -> float:
        """
        Get seconds to wait before a token is available.
        """
        self.refill_tokens(bucket)
        
        current_tokens = self.price_tokens if bucket == "price" else self.avail_tokens
        
        if current_tokens >= 1.0:
            return 0.0
        
        tokens_needed = 1.0 - current_tokens
        return tokens_needed / self.REFILL_RATE
    
    def is_paused(self) -> bool:
        """Check if property is currently paused due to 429."""
        if not self.paused_until:
            return False
        return datetime.utcnow() < self.paused_until
    
    def pause_on_429(self):
        """
        Pause the property due to 429 response.
        Uses exponential backoff based on pause_count.
        """
        self.pause_count += 1
        self.total_429s += 1
        self.last_429_at = datetime.utcnow()
        
        # Exponential backoff: 60s, 120s, 240s, 480s, max 600s
        pause_seconds = min(
            self.BASE_PAUSE_SECONDS * (2 ** (self.pause_count - 1)),
            self.MAX_PAUSE_SECONDS
        )
        self.paused_until = datetime.utcnow() + timedelta(seconds=pause_seconds)
    
    def clear_pause(self):
        """Clear pause state after successful request."""
        if self.paused_until and datetime.utcnow() >= self.paused_until:
            self.paused_until = None
            # Don't reset pause_count immediately - decay it slowly
            if self.pause_count > 0:
                self.pause_count = max(0, self.pause_count - 1)
    
    def __repr__(self):
        return f"<PropertyRateState {self.channex_property_id} price={self.price_tokens:.1f} avail={self.avail_tokens:.1f}>"
