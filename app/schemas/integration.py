"""
Channel Integration Schemas

Pydantic models for channel integration API requests and responses.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ==================
# Channel Connection
# ==================

class ChannelConnectionCreate(BaseModel):
    """Schema for creating a channel connection"""
    project_id: str = Field(..., description="Project to attach connection to")
    provider: str = Field(default="channex", description="Channel manager provider")
    api_key: str = Field(..., description="API key for the provider")
    channex_property_id: str = Field(..., description="Channex property ID")
    channex_group_id: Optional[str] = None
    webhook_secret: Optional[str] = None


class ChannelConnectionUpdate(BaseModel):
    """Schema for updating a channel connection"""
    api_key: Optional[str] = None
    channex_property_id: Optional[str] = None
    channex_group_id: Optional[str] = None
    webhook_secret: Optional[str] = None
    status: Optional[str] = None


class ChannelConnectionResponse(BaseModel):
    """Schema for channel connection response"""
    id: str
    project_id: str
    provider: str
    channex_property_id: Optional[str]
    channex_group_id: Optional[str]
    status: str
    last_sync_at: Optional[datetime]
    last_error: Optional[str]
    error_count: int
    created_at: datetime
    updated_at: datetime
    # Note: api_key is NOT exposed in responses
    
    class Config:
        from_attributes = True


class ChannelConnectionHealth(BaseModel):
    """Health status of a channel connection"""
    id: str
    provider: str
    status: str
    last_sync_at: Optional[datetime]
    last_error: Optional[str]
    error_count: int
    pending_events: int
    failed_events: int


# ==================
# External Mapping
# ==================

class ExternalMappingCreate(BaseModel):
    """Schema for creating an external mapping"""
    connection_id: str
    unit_id: str
    channex_room_type_id: str
    channex_rate_plan_id: str
    mapping_type: str = "unit_to_room"


class ExternalMappingUpdate(BaseModel):
    """Schema for updating an external mapping"""
    channex_room_type_id: Optional[str] = None
    channex_rate_plan_id: Optional[str] = None
    is_active: Optional[bool] = None


class ExternalMappingResponse(BaseModel):
    """Schema for external mapping response"""
    id: str
    connection_id: str
    unit_id: Optional[str]
    channex_room_type_id: Optional[str]
    channex_rate_plan_id: Optional[str]
    mapping_type: str
    is_active: bool
    last_price_sync_at: Optional[datetime]
    last_avail_sync_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================
# Integration Outbox
# ==================

class OutboxEventResponse(BaseModel):
    """Schema for outbox event response"""
    id: str
    connection_id: str
    event_type: str
    unit_id: Optional[str]
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class OutboxEventDetail(OutboxEventResponse):
    """Detailed outbox event with payload"""
    payload: Optional[Dict[str, Any]]
    response_data: Optional[Dict[str, Any]]


class OutboxRetryRequest(BaseModel):
    """Request to retry a failed event"""
    event_id: str


class OutboxBatchResult(BaseModel):
    """Result of processing a batch of events"""
    success_count: int
    failure_count: int
    processed_ids: List[str]


# ==================
# Integration Logs
# ==================

class IntegrationLogResponse(BaseModel):
    """Schema for integration log response"""
    id: str
    connection_id: Optional[str]
    log_type: str
    direction: str
    event_type: Optional[str]
    request_method: Optional[str]
    request_url: Optional[str]
    response_status: Optional[int]
    success: bool
    error_message: Optional[str]
    duration_ms: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================
# Webhook
# ==================

class ChannexWebhookPayload(BaseModel):
    """Expected Channex webhook payload structure"""
    event: str
    property_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    class Config:
        extra = "allow"  # Allow extra fields from Channex


class WebhookResponse(BaseModel):
    """Response for webhook processing"""
    success: bool
    action: str
    booking_id: Optional[str] = None
    message: Optional[str] = None


# ==================
# Sync Operations
# ==================

class SyncRequest(BaseModel):
    """Request to trigger a sync"""
    unit_id: Optional[str] = None  # If None, sync all units
    sync_type: str = Field(default="full", description="Type: 'full', 'prices', 'availability'")
    days_ahead: int = Field(default=365, ge=1, le=730)


class SyncStatusResponse(BaseModel):
    """Status of sync operations"""
    connection_id: str
    total_units: int
    synced_units: int
    pending_events: int
    failed_events: int
    last_sync_at: Optional[datetime]
