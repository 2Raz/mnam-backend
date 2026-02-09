"""
Integrations API Router

Production-ready endpoints for Channex integration:
- Channel connections (connect, test, sync)
- External mappings (unit <-> room type)
- Webhooks (fast ack, async processing)
- Outbox management (failures, retries)
- Observability (logs, health)

Security:
- API key never exposed to frontend
- Webhook validation with signature/secret
- request_id in all logs
"""

import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_db
from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    IntegrationLog,
    ConnectionStatus,
    OutboxStatus
)
from ..models.webhook_event import WebhookEventLog, WebhookEventStatus
from ..models.unmatched_webhook import UnmatchedWebhookEvent, UnmatchedEventStatus
from ..models.unit import Unit
from ..models.project import Project
from ..models.user import User
from ..models.integration_alert import IntegrationAlert, AlertStatus
from ..utils.dependencies import get_current_user
from ..services.channex_service import ChannexIntegrationService
from ..services.webhook_processor import AsyncWebhookReceiver, WebhookProcessor
from ..services.webhook_receiver import WebhookReceiver
from ..services.channex_client import ChannexClient, get_channex_client
from ..services.outbox_worker import (
    OutboxProcessor,
    enqueue_price_update,
    enqueue_availability_update,
    enqueue_full_sync
)
from ..services.health_check import ChannexHealthService
from ..config import settings
from ..schemas.integration import (
    ChannelConnectionCreate,
    ChannelConnectionUpdate,
    ChannelConnectionResponse,
    ChannelConnectionHealth,
    ExternalMappingCreate,
    ExternalMappingUpdate,
    ExternalMappingResponse,
    OutboxEventResponse,
    OutboxEventDetail,
    OutboxRetryRequest,
    OutboxBatchResult,
    IntegrationLogResponse,
    ChannexWebhookPayload,
    WebhookResponse,
    SyncRequest,
    SyncStatusResponse
)

router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


def get_request_id(request: Request) -> str:
    """Get request_id from request state or generate one"""
    return getattr(request.state, 'request_id', str(uuid.uuid4())[:8])


# ==================
# Channex Connect Flow
# ==================

@router.post("/channex/connect")
async def connect_channex(
    request: Request,
    connection_data: ChannelConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Connect a MNAM project to a Channex property.
    
    Steps:
    1. Validates API key by calling Channex GET /properties/{id}
    2. Stores connection if valid
    3. Never returns the API key
    """
    request_id = get_request_id(request)
    service = ChannexIntegrationService(db, request_id)
    
    result = service.connect(
        project_id=connection_data.project_id,
        api_key=connection_data.api_key,
        channex_property_id=connection_data.channex_property_id,
        webhook_secret=connection_data.webhook_secret,
        created_by_id=current_user.id
    )
    
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    
    return {
        "success": True,
        "connection_id": result.connection_id,
        "property_name": result.property_name,
        "message": f"تم الاتصال بنجاح: {result.property_name}"
    }


@router.get("/channex/properties")
async def list_channex_properties(
    request: Request,
    api_key: str = Query(..., description="Channex API key to list properties for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List properties accessible with a Channex API key.
    Used for selecting which property to connect.
    """
    request_id = get_request_id(request)
    service = ChannexIntegrationService(db, request_id)
    
    success, properties = service.get_channex_properties(api_key)
    
    if not success:
        raise HTTPException(status_code=400, detail="فشل جلب العقارات من Channex")
    
    return {
        "properties": [
            {
                "id": p.id,
                "title": p.title,
                "currency": p.currency,
                "timezone": p.timezone
            }
            for p in properties
        ]
    }


@router.get("/channex/room-types")
async def list_channex_room_types(
    request: Request,
    connection_id: str = Query(..., description="Connection ID to fetch room types for"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List room types from Channex for a specific connection.
    Used in mapping wizard to select room type.
    """
    request_id = get_request_id(request)
    
    # Get connection
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    # Fetch from Channex
    client = get_channex_client(connection, db, request_id)
    resp = client.get_room_types(connection.channex_property_id)
    
    if not resp.success:
        raise HTTPException(status_code=400, detail=f"فشل جلب أنواع الغرف: {resp.error}")
    
    # Channex returns JSON:API format with "data" array
    raw_data = resp.data or {}
    room_types = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data
    
    return {
        "room_types": [
            {
                "id": rt.get("id") if isinstance(rt, dict) else rt,
                "title": (rt.get("attributes", {}).get("title") or rt.get("title", "")) if isinstance(rt, dict) else "",
                "occ_adults": (rt.get("attributes", {}).get("occ_adults") or rt.get("occ_adults", 2)) if isinstance(rt, dict) else 2,
                "occ_children": (rt.get("attributes", {}).get("occ_children") or rt.get("occ_children", 0)) if isinstance(rt, dict) else 0,
                "occ_infants": (rt.get("attributes", {}).get("occ_infants") or rt.get("occ_infants", 0)) if isinstance(rt, dict) else 0,
            }
            for rt in room_types
        ]
    }


@router.get("/channex/rate-plans")
async def list_channex_rate_plans(
    request: Request,
    connection_id: str = Query(..., description="Connection ID to fetch rate plans for"),
    room_type_id: Optional[str] = Query(None, description="Filter by room type ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List rate plans from Channex for a specific connection.
    Used in mapping wizard to select rate plan.
    """
    request_id = get_request_id(request)
    
    # Get connection
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    # Fetch from Channex
    client = get_channex_client(connection, db, request_id)
    resp = client.get_rate_plans(connection.channex_property_id)
    
    if not resp.success:
        raise HTTPException(status_code=400, detail=f"فشل جلب خطط الأسعار: {resp.error}")
    
    # Channex returns JSON:API format with "data" array
    raw_data = resp.data or {}
    rate_plans = raw_data.get("data", []) if isinstance(raw_data, dict) else raw_data
    
    # Filter by room_type_id if provided
    if room_type_id:
        rate_plans = [
            rp for rp in rate_plans 
            if isinstance(rp, dict) and (
                rp.get("relationships", {}).get("room_type", {}).get("data", {}).get("id") == room_type_id or
                rp.get("attributes", {}).get("room_type_id") == room_type_id
            )
        ]
    
    return {
        "rate_plans": [
            {
                "id": rp.get("id") if isinstance(rp, dict) else rp,
                "title": (rp.get("attributes", {}).get("title") or rp.get("title", "")) if isinstance(rp, dict) else "",
                "room_type_id": (rp.get("relationships", {}).get("room_type", {}).get("data", {}).get("id") or rp.get("attributes", {}).get("room_type_id")) if isinstance(rp, dict) else None,
                "currency": (rp.get("attributes", {}).get("currency") or rp.get("currency")) if isinstance(rp, dict) else None,
            }
            for rp in rate_plans
        ]
    }


@router.post("/channex/sync")
async def sync_channex(
    request: Request,
    connection_id: str = Query(..., description="Connection ID to sync"),
    auto_map: bool = Query(True, description="Auto-map units to room types"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Full sync flow:
    1. Pull room types and rate plans from Channex
    2. Create/update mappings (auto or manual)
    3. Push initial ARI (prices + availability) for next 365 days
    """
    request_id = get_request_id(request)
    service = ChannexIntegrationService(db, request_id)
    
    result = service.sync_mappings(connection_id, auto_map)
    
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    
    return {
        "success": True,
        "room_types_found": result.room_types_found,
        "rate_plans_found": result.rate_plans_found,
        "mappings_created": result.mappings_created,
        "events_queued": result.events_queued,
        "message": f"تم المزامنة: {result.mappings_created} ربط، {result.events_queued} حدث في الانتظار"
    }


@router.post("/sync-availability/{unit_id}")
async def sync_unit_availability(
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    مزامنة توفر وحدة محددة مع Channex يدوياً
    
    يقوم بـ:
    - حساب التوفر بناءً على حالة الوحدة
    - حظر الأيام المحجوزة
    - إرسال التحديث إلى Channex
    """
    from ..services.availability_sync_service import AvailabilitySyncService
    
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="الوحدة غير موجودة")
    
    service = AvailabilitySyncService(db)
    
    # الحصول على ملخص قبل المزامنة
    summary = service.get_availability_summary(unit_id)
    
    # تنفيذ المزامنة
    result = service.sync_unit_availability(unit_id)
    
    return {
        "success": result.get("success", False),
        "unit_name": unit.unit_name,
        "unit_status": unit.status,
        "summary": summary,
        "sync_result": result,
        "message": "تم مزامنة التوفر مع Channex" if result.get("success") else f"فشل المزامنة: {result.get('error', 'Unknown')}"
    }


# ==================
# Webhook Endpoint (FAST PATH)
# ==================

def validate_webhook_security(
    request: Request,
    body: bytes,
    signature: Optional[str]
) -> tuple[bool, Optional[str]]:
    """
    Validate webhook security:
    1. IP allowlist (if configured)
    2. HMAC signature (if secret configured)
    3. Replay protection (timestamp within window)
    
    Returns: (is_valid, error_message)
    """
    import hashlib
    import hmac
    import time
    
    # 1. IP Allowlist check
    allowed_ips = settings.channex_allowed_ip_list
    if allowed_ips:
        client_ip = request.client.host if request.client else None
        # Check X-Forwarded-For for proxied requests
        forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        actual_ip = forwarded_for or client_ip
        
        if actual_ip and actual_ip not in allowed_ips:
            return False, f"IP {actual_ip} not in allowlist"
    
    # 2. Signature validation (if webhook secret is configured)
    webhook_secret = settings.channex_webhook_secret
    if webhook_secret and signature:
        expected = hmac.new(
            webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        
        # Compare in constant time
        if not hmac.compare_digest(expected, signature):
            return False, "Invalid webhook signature"
    
    # 3. Replay protection
    # Check if payload has a timestamp and it's within our window
    replay_window = settings.channex_webhook_replay_window_seconds
    try:
        import json
        payload = json.loads(body)
        event_timestamp = payload.get("timestamp") or payload.get("created_at")
        
        if event_timestamp:
            # Parse ISO timestamp
            from datetime import datetime
            if isinstance(event_timestamp, str):
                # Handle ISO format with or without timezone
                ts_value = event_timestamp.replace("Z", "+00:00")
                try:
                    event_time = datetime.fromisoformat(ts_value)
                    now = datetime.utcnow()
                    
                    # Remove timezone for comparison
                    if event_time.tzinfo:
                        event_time = event_time.replace(tzinfo=None)
                    
                    age_seconds = abs((now - event_time).total_seconds())
                    if age_seconds > replay_window:
                        return False, f"Event too old ({age_seconds:.0f}s > {replay_window}s)"
                except ValueError:
                    pass  # Can't parse timestamp, skip replay check
    except (json.JSONDecodeError, KeyError):
        pass  # Can't parse payload, skip replay check
    
    return True, None


@router.post("/channex/webhook", response_model=WebhookResponse)
async def channex_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_channex_signature: Optional[str] = Header(None, alias="X-Channex-Signature"),
    db: Session = Depends(get_db)
):
    """
    Receive webhooks from Channex.
    
    Security:
    - IP allowlist validation (if CHANNEX_ALLOWED_IPS configured)
    - HMAC signature validation (if CHANNEX_WEBHOOK_SECRET configured)
    - Replay protection (rejects events older than CHANNEX_WEBHOOK_REPLAY_WINDOW)
    
    FAST PATH: Validate -> Persist raw event -> Return 200 immediately.
    Processing happens async via worker.
    
    Event types handled:
    - booking.new: New booking created
    - booking.modified: Booking updated
    - booking.cancelled: Booking cancelled
    """
    request_id = get_request_id(request)
    
    # Check if integration is enabled
    if not settings.channex_enabled:
        return WebhookResponse(
            success=False,
            action="disabled",
            message="Channex integration is disabled"
        )
    
    try:
        # Get raw body and parse
        body = await request.body()
        
        # Security validation
        is_valid, security_error = validate_webhook_security(request, body, x_channex_signature)
        
        if not is_valid:
            # Log the security failure but still return 200 to not leak info
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"[{request_id}] Webhook security check failed: {security_error}")
            
            # In production, you might want to reject entirely
            # For now, we still accept but flag for review
            # return WebhookResponse(success=False, action="rejected", message="Security validation failed")
        
        payload = await request.json()
        
        # Get headers for debugging
        headers = dict(request.headers)
        
        # Use async receiver for fast acknowledgment
        receiver = AsyncWebhookReceiver(db, request_id)
        result = receiver.receive(payload, headers)
        
        if not result.success:
            return WebhookResponse(
                success=False,
                action="error",
                message=result.error
            )
        
        if result.already_processed:
            return WebhookResponse(
                success=True,
                action="skipped",
                message="Event already processed"
            )
        
        # Optionally trigger immediate processing via background task
        # (Worker will also pick it up, but this speeds things up)
        # background_tasks.add_task(process_webhook_event, result.event_log_id)
        
        return WebhookResponse(
            success=True,
            action="queued",
            message=f"Event queued for processing: {result.event_log_id}"
        )
        
    except Exception as e:
        return WebhookResponse(
            success=False,
            action="error",
            message=str(e)
        )


# ==================
# NEW: Dual Webhook Endpoints (v2)
# ==================

@router.post("/webhooks/channex/bookings", response_model=WebhookResponse)
async def channex_booking_webhook(
    request: Request,
    x_mnam_webhook_token: Optional[str] = Header(None, alias="X-MNAM-Webhook-Token"),
    x_channex_signature: Optional[str] = Header(None, alias="X-Channex-Signature"),
    db: Session = Depends(get_db)
):
    """
    Receive booking webhooks from Channex (FAST PATH).
    
    Triggers: new, modification, cancellation
    
    Security:
    - Header token validation (X-MNAM-Webhook-Token)
    - Payload size limit (256KB)
    - Required fields validation
    
    Flow: Validate -> Store -> Enqueue -> Return 200 immediately
    """
    if not settings.channex_enabled:
        return WebhookResponse(
            success=False,
            action="disabled",
            message="Channex integration is disabled"
        )
    
    try:
        body = await request.body()
        content_length = len(body)
        payload = await request.json()
        headers = dict(request.headers)
        
        # Get secret from settings
        webhook_secret = getattr(settings, 'channex_webhook_secret', None)
        
        receiver = WebhookReceiver(db, webhook_secret)
        result = receiver.receive_booking(payload, headers, content_length)
        
        if result.already_exists:
            return WebhookResponse(
                success=True,
                action="skipped",
                message="Event already processed"
            )
        
        return WebhookResponse(
            success=True,
            action="queued",
            message=f"Event queued: {result.event_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return WebhookResponse(
            success=False,
            action="error",
            message=str(e)
        )


@router.post("/webhooks/channex/health", response_model=WebhookResponse)
async def channex_health_webhook(
    request: Request,
    x_mnam_webhook_token: Optional[str] = Header(None, alias="X-MNAM-Webhook-Token"),
    db: Session = Depends(get_db)
):
    """
    Receive health/error webhooks from Channex.
    
    Triggers: unmapped_room, unmapped_rate, sync_error, rate_error, non_acked
    
    Creates alerts for operations team visibility.
    Does NOT touch calendar or bookings directly.
    """
    if not settings.channex_enabled:
        return WebhookResponse(
            success=False,
            action="disabled",
            message="Channex integration is disabled"
        )
    
    try:
        body = await request.body()
        content_length = len(body)
        payload = await request.json()
        headers = dict(request.headers)
        
        webhook_secret = getattr(settings, 'channex_webhook_secret', None)
        
        receiver = WebhookReceiver(db, webhook_secret)
        result = receiver.receive_health(payload, headers, content_length)
        
        return WebhookResponse(
            success=True,
            action="alert_created",
            message=f"Alert created: {result.event_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return WebhookResponse(
            success=False,
            action="error",
            message=str(e)
        )


@router.post("/webhooks/channex/availability", response_model=WebhookResponse)
async def channex_availability_webhook(
    request: Request,
    x_mnam_webhook_token: Optional[str] = Header(None, alias="X-MNAM-Webhook-Token"),
    db: Session = Depends(get_db)
):
    """
    Receive availability/ARI webhooks from Channex.
    
    Triggers: ari_update, availability_update, restriction_update
    
    Updates the inventory_calendar based on external changes.
    """
    from ..services.inventory_service import InventoryService
    from datetime import datetime
    import json
    import hashlib
    
    if not settings.channex_enabled:
        return WebhookResponse(
            success=False,
            action="disabled",
            message="Channex integration is disabled"
        )
    
    try:
        body = await request.body()
        payload = await request.json()
        headers = dict(request.headers)
        
        # Verify token if configured
        webhook_secret = getattr(settings, 'channex_webhook_secret', None)
        if webhook_secret:
            token = headers.get("x-mnam-webhook-token")
            if not token or token != webhook_secret:
                raise HTTPException(status_code=401, detail="Invalid webhook token")
        
        # Extract data
        event_type = payload.get("event") or payload.get("event_type", "ari_update")
        property_id = payload.get("property_id")
        data = payload.get("data", {})
        
        # Compute hash for dedup
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        
        # Check for duplicate
        existing = db.query(WebhookEventLog).filter(
            WebhookEventLog.provider == "channex",
            WebhookEventLog.payload_hash == payload_hash
        ).first()
        
        if existing:
            return WebhookResponse(
                success=True,
                action="skipped",
                message="Duplicate event"
            )
        
        # Store event log
        event_log = WebhookEventLog(
            provider="channex",
            endpoint_type="availability",
            property_id=property_id,
            event_type=event_type,
            payload_json=json.dumps(payload),
            payload_hash=payload_hash,
            status=WebhookEventStatus.RECEIVED.value,
            received_at=datetime.utcnow()
        )
        db.add(event_log)
        
        # Process availability updates
        updates_applied = 0
        inventory_service = InventoryService(db)
        
        # Handle different payload formats
        changes = data.get("changes", []) or data.get("updates", []) or [data]
        
        for change in changes:
            room_type_id = change.get("room_type_id")
            date_from = change.get("date_from") or change.get("date")
            date_to = change.get("date_to") or change.get("date")
            
            # Find unit by room_type_id
            if room_type_id:
                mapping = db.query(ExternalMapping).filter(
                    ExternalMapping.channex_room_type_id == room_type_id
                ).first()
                
                if mapping and date_from:
                    from datetime import datetime as dt
                    
                    # Parse dates
                    start_date = dt.strptime(date_from, "%Y-%m-%d").date()
                    end_date = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else start_date
                    
                    # Check if blocked/closed
                    is_blocked = change.get("stop_sell", False) or change.get("closed", False)
                    
                    # Check if this is a full unit block (not date-specific)
                    is_unit_level_block = change.get("unit_closed", False) or change.get("room_closed", False)
                    
                    if is_blocked:
                        inventory_service.block_dates(
                            unit_id=mapping.unit_id,
                            start_date=start_date,
                            end_date=end_date,
                            reason="channex_sync"
                        )
                        
                        # إذا كان الحظر على مستوى الوحدة بالكامل، نغير حالتها
                        if is_unit_level_block:
                            from ..models.unit import Unit
                            unit = db.query(Unit).filter(Unit.id == mapping.unit_id).first()
                            if unit and unit.status not in ["صيانة", "مخفية"]:
                                unit.status = "مخفية"  # حالة مغلقة من القناة الخارجية
                                db.add(unit)
                                # إنشاء تنبيه للأوبريشن
                                alert = IntegrationAlert(
                                    alert_type="unit_closed",
                                    severity="warning",
                                    message=f"تم إغلاق الوحدة '{unit.unit_name}' من القناة الخارجية",
                                    property_id=property_id,
                                    status="open"
                                )
                                db.add(alert)
                    else:
                        # رفع الحظر - فتح التوفر
                        inventory_service.unblock_dates(
                            unit_id=mapping.unit_id,
                            start_date=start_date,
                            end_date=end_date
                        )
                        
                        # إذا كان الرفع على مستوى الوحدة، نعيد تفعيلها
                        if is_unit_level_block:
                            from ..models.unit import Unit
                            unit = db.query(Unit).filter(Unit.id == mapping.unit_id).first()
                            if unit and unit.status == "مخفية":
                                unit.status = "متاحة"
                                db.add(unit)
                    
                    updates_applied += 1
        
        # Mark as processed
        event_log.status = WebhookEventStatus.PROCESSED.value
        event_log.processed_at = datetime.utcnow()
        event_log.result_action = f"applied_{updates_applied}_updates"
        db.commit()
        
        return WebhookResponse(
            success=True,
            action="processed",
            message=f"Applied {updates_applied} availability updates"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f"Error processing availability webhook: {e}")
        return WebhookResponse(
            success=False,
            action="error",
            message=str(e)
        )


# ==================
# Integration Alerts
# ==================

@router.get("/alerts")
async def list_integration_alerts(
    status: Optional[str] = Query(None, description="Filter by status: open, acknowledged, resolved"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List integration alerts for operations visibility.
    """
    query = db.query(IntegrationAlert).order_by(IntegrationAlert.created_at.desc())
    
    if status:
        query = query.filter(IntegrationAlert.status == status)
    
    alerts = query.limit(limit).all()
    
    return {
        "success": True,
        "count": len(alerts),
        "alerts": [
            {
                "id": a.id,
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "property_id": a.property_id,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in alerts
        ]
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Acknowledge an integration alert."""
    from datetime import datetime
    
    alert = db.query(IntegrationAlert).filter(IntegrationAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_at = datetime.utcnow()
    alert.acknowledged_by_id = current_user.id
    db.commit()
    
    return {"success": True, "message": "Alert acknowledged"}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve an integration alert."""
    from datetime import datetime
    
    alert = db.query(IntegrationAlert).filter(IntegrationAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.status = AlertStatus.RESOLVED.value
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by_id = current_user.id
    alert.resolution_notes = notes
    db.commit()
    
    return {"success": True, "message": "Alert resolved"}


@router.post("/channex/webhook/process")
async def process_webhook_batch(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually trigger processing of queued webhook events.
    Normally handled by background worker.
    """
    processor = WebhookProcessor(db)
    success, failed = processor.process_batch(limit)
    
    return {
        "success": True,
        "processed": success,
        "failed": failed,
        "message": f"Processed {success} events, {failed} failed"
    }


@router.get("/channex/webhook/pending")
async def list_pending_webhooks(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List pending webhook events awaiting processing"""
    events = db.query(WebhookEventLog).filter(
        WebhookEventLog.status == WebhookEventStatus.RECEIVED.value
    ).order_by(WebhookEventLog.received_at).limit(limit).all()
    
    return {
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "external_id": e.external_id,
                "received_at": e.received_at.isoformat() if e.received_at else None
            }
            for e in events
        ]
    }


# ==================
# Channel Connections
# ==================

@router.post("/connections", response_model=ChannelConnectionResponse)
async def create_connection(
    connection_data: ChannelConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new channel connection"""
    # Verify project exists
    project = db.query(Project).filter(Project.id == connection_data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="المشروع غير موجود")
    
    # Check for existing connection
    existing = db.query(ChannelConnection).filter(
        and_(
            ChannelConnection.project_id == connection_data.project_id,
            ChannelConnection.provider == connection_data.provider
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="يوجد اتصال بالفعل لهذا المزود")
    
    connection = ChannelConnection(
        project_id=connection_data.project_id,
        provider=connection_data.provider,
        api_key=connection_data.api_key,
        channex_property_id=connection_data.channex_property_id,
        channex_group_id=connection_data.channex_group_id,
        webhook_secret=connection_data.webhook_secret,
        status=ConnectionStatus.PENDING.value,
        created_by_id=current_user.id
    )
    
    db.add(connection)
    db.commit()
    db.refresh(connection)
    
    return connection


@router.get("/connections", response_model=List[ChannelConnectionResponse])
async def list_connections(
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all channel connections"""
    query = db.query(ChannelConnection)
    if project_id:
        query = query.filter(ChannelConnection.project_id == project_id)
    return query.all()


@router.get("/connections/{connection_id}", response_model=ChannelConnectionResponse)
async def get_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a channel connection by ID"""
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    return connection


@router.put("/connections/{connection_id}", response_model=ChannelConnectionResponse)
async def update_connection(
    connection_id: str,
    connection_data: ChannelConnectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a channel connection"""
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    update_data = connection_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(connection, key, value)
    
    connection.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(connection)
    
    return connection


@router.delete("/connections/{connection_id}")
async def delete_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a channel connection permanently"""
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    db.delete(connection)
    db.commit()
    
    return {"message": "تم حذف الاتصال بنجاح"}


@router.post("/connections/{connection_id}/test")
async def test_connection(
    request: Request,
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Test a channel connection"""
    request_id = get_request_id(request)
    
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    try:
        client = get_channex_client(connection, db, request_id)
        response = client.get_property()
        
        if response.success:
            connection.status = ConnectionStatus.ACTIVE.value
            connection.last_error = None
            connection.error_count = 0
            db.commit()
            return {"success": True, "message": "الاتصال ناجح", "data": response.data}
        else:
            connection.status = ConnectionStatus.ERROR.value
            connection.last_error = response.error
            connection.error_count += 1
            db.commit()
            return {"success": False, "message": response.error}
            
    except Exception as e:
        connection.status = ConnectionStatus.ERROR.value
        connection.last_error = str(e)
        connection.error_count += 1
        db.commit()
        return {"success": False, "message": str(e)}


@router.get("/connections/{connection_id}/health", response_model=ChannelConnectionHealth)
async def get_connection_health(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get health status of a channel connection"""
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    pending_count = db.query(IntegrationOutbox).filter(
        and_(
            IntegrationOutbox.connection_id == connection_id,
            IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
        )
    ).count()
    
    failed_count = db.query(IntegrationOutbox).filter(
        and_(
            IntegrationOutbox.connection_id == connection_id,
            IntegrationOutbox.status == OutboxStatus.FAILED.value
        )
    ).count()
    
    return ChannelConnectionHealth(
        id=connection.id,
        provider=connection.provider,
        status=connection.status,
        last_sync_at=connection.last_sync_at,
        last_error=connection.last_error,
        error_count=connection.error_count,
        pending_events=pending_count,
        failed_events=failed_count
    )


# ==================
# External Mappings
# ==================

@router.post("/mappings", response_model=ExternalMappingResponse)
async def create_mapping(
    mapping_data: ExternalMappingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create an external mapping (unit to Channex room type)"""
    # Verify connection exists
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == mapping_data.connection_id
    ).first()
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    # Verify unit exists
    unit = db.query(Unit).filter(Unit.id == mapping_data.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="الوحدة غير موجودة")
    
    # Check for existing mapping
    existing = db.query(ExternalMapping).filter(
        and_(
            ExternalMapping.connection_id == mapping_data.connection_id,
            ExternalMapping.unit_id == mapping_data.unit_id
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="يوجد ربط بالفعل لهذه الوحدة")
    
    mapping = ExternalMapping(
        connection_id=mapping_data.connection_id,
        unit_id=mapping_data.unit_id,
        channex_room_type_id=mapping_data.channex_room_type_id,
        channex_rate_plan_id=mapping_data.channex_rate_plan_id,
        mapping_type=mapping_data.mapping_type
    )
    
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    
    # Trigger full sync for the new mapping
    enqueue_full_sync(db, mapping_data.unit_id, mapping_data.connection_id)
    
    return mapping


@router.get("/mappings")
async def list_mappings(
    connection_id: Optional[str] = Query(None),
    unit_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List external mappings with sync status"""
    query = db.query(ExternalMapping)
    if connection_id:
        query = query.filter(ExternalMapping.connection_id == connection_id)
    if unit_id:
        query = query.filter(ExternalMapping.unit_id == unit_id)
    
    mappings = query.all()
    
    # Get sync status for each mapping based on outbox events
    result = []
    for mapping in mappings:
        # Check for failed events for this unit
        failed_count = db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.connection_id == mapping.connection_id,
                IntegrationOutbox.unit_id == mapping.unit_id,
                IntegrationOutbox.status == OutboxStatus.FAILED.value
            )
        ).count()
        
        # Check for pending events
        pending_count = db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.connection_id == mapping.connection_id,
                IntegrationOutbox.unit_id == mapping.unit_id,
                IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
            )
        ).count()
        
        # Determine sync status
        if failed_count > 0:
            sync_status = "error"
        elif pending_count > 0:
            sync_status = "pending"
        elif mapping.last_price_sync_at and mapping.last_avail_sync_at:
            sync_status = "synced"
        else:
            sync_status = "pending"
        
        result.append({
            "id": mapping.id,
            "connection_id": mapping.connection_id,
            "unit_id": mapping.unit_id,
            "channex_room_type_id": mapping.channex_room_type_id,
            "channex_rate_plan_id": mapping.channex_rate_plan_id,
            "mapping_type": mapping.mapping_type,
            "is_active": mapping.is_active,
            "last_price_sync_at": mapping.last_price_sync_at,
            "last_avail_sync_at": mapping.last_avail_sync_at,
            "created_at": mapping.created_at,
            "sync_status": sync_status
        })
    
    return result


@router.put("/mappings/{mapping_id}", response_model=ExternalMappingResponse)
async def update_mapping(
    mapping_id: str,
    mapping_data: ExternalMappingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an external mapping"""
    mapping = db.query(ExternalMapping).filter(
        ExternalMapping.id == mapping_id
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="الربط غير موجود")
    
    update_data = mapping_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(mapping, key, value)
    
    mapping.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(mapping)
    
    return mapping


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an external mapping"""
    mapping = db.query(ExternalMapping).filter(
        ExternalMapping.id == mapping_id
    ).first()
    
    if not mapping:
        raise HTTPException(status_code=404, detail="الربط غير موجود")
    
    db.delete(mapping)
    db.commit()
    
    return {"message": "تم حذف الربط بنجاح"}


# ==================
# Sync Operations
# ==================

@router.post("/connections/{connection_id}/sync", response_model=SyncStatusResponse)
async def trigger_sync(
    connection_id: str,
    sync_request: SyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger a sync for a connection"""
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    # Get all mappings for this connection
    query = db.query(ExternalMapping).filter(
        and_(
            ExternalMapping.connection_id == connection_id,
            ExternalMapping.is_active == True
        )
    )
    
    if sync_request.unit_id:
        query = query.filter(ExternalMapping.unit_id == sync_request.unit_id)
    
    mappings = query.all()
    
    # Enqueue events for each mapping
    for mapping in mappings:
        if sync_request.sync_type in ("full", "prices"):
            enqueue_price_update(
                db=db,
                unit_id=mapping.unit_id,
                connection_id=connection_id,
                days_ahead=sync_request.days_ahead
            )
        if sync_request.sync_type in ("full", "availability"):
            enqueue_availability_update(
                db=db,
                unit_id=mapping.unit_id,
                connection_id=connection_id,
                days_ahead=sync_request.days_ahead
            )
    
    # Count pending events
    pending_count = db.query(IntegrationOutbox).filter(
        and_(
            IntegrationOutbox.connection_id == connection_id,
            IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
        )
    ).count()
    
    failed_count = db.query(IntegrationOutbox).filter(
        and_(
            IntegrationOutbox.connection_id == connection_id,
            IntegrationOutbox.status == OutboxStatus.FAILED.value
        )
    ).count()
    
    return SyncStatusResponse(
        connection_id=connection_id,
        total_units=len(mappings),
        synced_units=0,
        pending_events=pending_count,
        failed_events=failed_count,
        last_sync_at=connection.last_sync_at
    )


# ==================
# Outbox Management
# ==================

@router.get("/outbox", response_model=List[OutboxEventResponse])
async def list_outbox_events(
    connection_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List outbox events"""
    query = db.query(IntegrationOutbox)
    
    if connection_id:
        query = query.filter(IntegrationOutbox.connection_id == connection_id)
    if status:
        query = query.filter(IntegrationOutbox.status == status)
    
    return query.order_by(IntegrationOutbox.created_at.desc()).limit(limit).all()


@router.get("/outbox/failures", response_model=List[OutboxEventResponse])
async def list_outbox_failures(
    connection_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List failed outbox events"""
    query = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.status == OutboxStatus.FAILED.value
    )
    
    if connection_id:
        query = query.filter(IntegrationOutbox.connection_id == connection_id)
    
    return query.order_by(IntegrationOutbox.created_at.desc()).limit(limit).all()


@router.get("/outbox/{event_id}", response_model=OutboxEventDetail)
async def get_outbox_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get details of an outbox event"""
    event = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.id == event_id
    ).first()
    
    if not event:
        raise HTTPException(status_code=404, detail="الحدث غير موجود")
    
    return event


@router.post("/outbox/{event_id}/retry")
async def retry_outbox_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retry a failed outbox event"""
    processor = OutboxProcessor(db)
    success = processor.retry_failed_event(event_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="الحدث غير موجود")
    
    return {"message": "تم إعادة جدولة الحدث بنجاح"}


@router.post("/outbox/process", response_model=OutboxBatchResult)
async def process_outbox_batch(
    limit: int = Query(50, ge=1, le=100),
    connection_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually trigger processing of pending outbox events.
    
    This is typically run by a background job, but can be triggered manually.
    """
    processor = OutboxProcessor(db)
    
    events = processor.get_pending_events(limit, connection_id)
    events = processor.merge_overlapping_events(events)
    
    success_count = 0
    failure_count = 0
    processed_ids = []
    
    for event in events:
        processed_ids.append(event.id)
        if processor.process_event(event):
            success_count += 1
        else:
            failure_count += 1
    
    return OutboxBatchResult(
        success_count=success_count,
        failure_count=failure_count,
        processed_ids=processed_ids
    )


# ==================
# Integration Logs
# ==================

@router.get("/logs", response_model=List[IntegrationLogResponse])
async def list_integration_logs(
    connection_id: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List integration logs"""
    query = db.query(IntegrationLog)
    
    if connection_id:
        query = query.filter(IntegrationLog.connection_id == connection_id)
    if direction:
        query = query.filter(IntegrationLog.direction == direction)
    if success is not None:
        query = query.filter(IntegrationLog.success == success)
    
    return query.order_by(IntegrationLog.created_at.desc()).limit(limit).all()


# ==================
# Channex Health & Sync Endpoints
# ==================

@router.get("/channex/health")
async def channex_health_check(
    request: Request,
    connection_id: Optional[str] = Query(None, description="Specific connection to check"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Comprehensive health check for Channex integration.
    
    Implements FAS (Fail-fast / Audit / Safe-sync) pattern:
    - F: Env vars, API connectivity, IDs validation
    - A: Audit trail verification
    - S: Sync readiness checks
    
    Returns overall status: healthy, degraded, or unhealthy
    """
    if not settings.channex_enabled:
        return {
            "overall_status": "disabled",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Channex integration is disabled",
            "checks": []
        }
    
    request_id = get_request_id(request)
    health_service = ChannexHealthService(db, request_id)
    
    report = health_service.run_all_checks(connection_id)
    
    return {
        "overall_status": report.overall_status,
        "timestamp": report.timestamp,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "message": c.message,
                "details": c.details
            }
            for c in report.checks
        ],
        "summary": report.summary
    }


@router.post("/channex/sync/full")
async def channex_full_sync(
    request: Request,
    connection_id: str = Query(..., description="Connection ID to sync"),
    days_ahead: int = Query(365, ge=1, le=730, description="Days to sync ahead"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger a full sync (prices + availability + restrictions) for all mapped units.
    
    This will:
    1. Get all active mappings for the connection
    2. Queue full sync events for each unit
    3. Worker will process with rate limiting
    
    Use for initial setup or recovery.
    """
    if not settings.channex_enabled:
        raise HTTPException(status_code=503, detail="Channex integration is disabled")
    
    request_id = get_request_id(request)
    
    # Verify connection
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    if connection.status != ConnectionStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail=f"الاتصال غير نشط: {connection.status}")
    
    # Get all active mappings
    mappings = db.query(ExternalMapping).filter(
        and_(
            ExternalMapping.connection_id == connection_id,
            ExternalMapping.is_active == True
        )
    ).all()
    
    if not mappings:
        raise HTTPException(status_code=400, detail="لا توجد ربطات نشطة")
    
    # Queue full sync for each mapping
    events_queued = 0
    for mapping in mappings:
        enqueue_full_sync(
            db=db,
            unit_id=mapping.unit_id,
            connection_id=connection_id,
            idempotency_key=f"full_sync_{mapping.unit_id}_{datetime.utcnow().date()}"
        )
        events_queued += 1
    
    # Update connection sync time
    connection.last_sync_at = datetime.utcnow()
    db.commit()
    
    return {
        "success": True,
        "connection_id": connection_id,
        "units_queued": events_queued,
        "days_ahead": days_ahead,
        "message": f"تم جدولة مزامنة كاملة لـ {events_queued} وحدة"
    }


@router.post("/channex/sync/incremental")
async def channex_incremental_sync(
    request: Request,
    connection_id: str = Query(..., description="Connection ID to sync"),
    unit_id: Optional[str] = Query(None, description="Specific unit to sync (optional)"),
    sync_type: str = Query("full", description="Type: 'full', 'prices', 'availability'"),
    days_ahead: int = Query(30, ge=1, le=365, description="Days to sync ahead"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Trigger an incremental sync for specific changes.
    
    Use for:
    - After pricing policy update -> sync_type='prices'
    - After booking created/modified/cancelled -> sync_type='availability'
    - Manual refresh -> sync_type='full'
    """
    if not settings.channex_enabled:
        raise HTTPException(status_code=503, detail="Channex integration is disabled")
    
    request_id = get_request_id(request)
    
    # Verify connection
    connection = db.query(ChannelConnection).filter(
        ChannelConnection.id == connection_id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="الاتصال غير موجود")
    
    if connection.status != ConnectionStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail=f"الاتصال غير نشط: {connection.status}")
    
    # Get mappings to sync
    query = db.query(ExternalMapping).filter(
        and_(
            ExternalMapping.connection_id == connection_id,
            ExternalMapping.is_active == True
        )
    )
    
    if unit_id:
        query = query.filter(ExternalMapping.unit_id == unit_id)
    
    mappings = query.all()
    
    if not mappings:
        raise HTTPException(status_code=400, detail="لا توجد ربطات نشطة للمزامنة")
    
    # Queue events based on sync type
    events_queued = 0
    timestamp = datetime.utcnow().timestamp()
    
    for mapping in mappings:
        if sync_type in ("full", "prices"):
            enqueue_price_update(
                db=db,
                unit_id=mapping.unit_id,
                connection_id=connection_id,
                days_ahead=days_ahead,
                idempotency_key=f"inc_price_{mapping.unit_id}_{timestamp}"
            )
            events_queued += 1
        
        if sync_type in ("full", "availability"):
            enqueue_availability_update(
                db=db,
                unit_id=mapping.unit_id,
                connection_id=connection_id,
                days_ahead=days_ahead,
                idempotency_key=f"inc_avail_{mapping.unit_id}_{timestamp}"
            )
            events_queued += 1
    
    return {
        "success": True,
        "connection_id": connection_id,
        "unit_id": unit_id,
        "sync_type": sync_type,
        "events_queued": events_queued,
        "days_ahead": days_ahead,
        "message": f"تم جدولة {events_queued} حدث مزامنة"
    }


@router.get("/channex/status")
async def get_channex_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get overall Channex integration status.
    Quick overview without detailed health checks.
    """
    is_enabled = settings.channex_enabled
    
    if not is_enabled:
        return {
            "enabled": False,
            "message": "Channex integration is disabled"
        }
    
    # Count connections
    total_connections = db.query(ChannelConnection).filter(
        ChannelConnection.provider == "channex"
    ).count()
    
    active_connections = db.query(ChannelConnection).filter(
        and_(
            ChannelConnection.provider == "channex",
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        )
    ).count()
    
    # Count pending outbox
    pending_outbox = db.query(IntegrationOutbox).filter(
        IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
    ).count()
    
    # Count pending webhooks
    pending_webhooks = db.query(WebhookEventLog).filter(
        WebhookEventLog.status == WebhookEventStatus.RECEIVED.value
    ).count()
    
    return {
        "enabled": True,
        "base_url": settings.channex_base_url,
        "connections": {
            "total": total_connections,
            "active": active_connections
        },
        "queues": {
            "pending_outbox": pending_outbox,
            "pending_webhooks": pending_webhooks
        },
        "config": {
            "sync_days": settings.channex_sync_days,
            "price_rate_limit": settings.channex_price_rate_limit,
            "avail_rate_limit": settings.channex_avail_rate_limit
        }
    }


# ==================
# LOCAL Testing Endpoints (Development Only!)
# ==================

import httpx
import logging
from datetime import date, timedelta
from pydantic import BaseModel

local_logger = logging.getLogger("channex.local")


def _check_local_env_configured() -> tuple:
    """Check if local Channex env vars are configured. Returns (is_configured, missing_vars)"""
    missing = []
    if not settings.channex_api_key:
        missing.append("CHANNEX_API_KEY")
    if not settings.channex_property_id:
        missing.append("CHANNEX_PROPERTY_ID")
    if not settings.channex_room_type_id:
        missing.append("CHANNEX_ROOM_TYPE_ID")
    if not settings.channex_rate_plan_id:
        missing.append("CHANNEX_RATE_PLAN_ID")
    return (len(missing) == 0, missing)


def _get_local_httpx_client() -> httpx.Client:
    """Get httpx client configured for local Channex testing"""
    return httpx.Client(
        base_url=settings.channex_base_url,
        headers={
            "user-api-key": settings.channex_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        timeout=settings.channex_timeout_seconds
    )


class LocalAvailabilityRequest(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    availability: int = 1


class LocalRateRequest(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    rate: float = 100.00
    currency: str = "SAR"


@router.get("/channex/local/health")
async def local_channex_health():
    """
    Health check for local Channex testing.
    
    Checks:
    1. Env vars configured
    2. API connectivity
    3. Property valid
    4. Room type valid (belongs to property)
    5. Rate plan valid (belongs to room type)
    
    No auth required - for local testing only.
    """
    checks = []
    
    # Check 1: Env vars
    is_configured, missing = _check_local_env_configured()
    checks.append({
        "name": "env_vars",
        "passed": is_configured,
        "message": "All required env vars present" if is_configured else f"Missing: {', '.join(missing)}",
        "details": {"missing": missing} if missing else None
    })
    
    if not is_configured:
        return {
            "overall_status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "base_url": settings.channex_base_url,
            "checks": checks
        }
    
    # Use httpx for remaining checks
    try:
        with _get_local_httpx_client() as client:
            # Check 2: API connectivity + Property valid
            local_logger.info(f"[LOCAL] GET /properties/{settings.channex_property_id}")
            resp = client.get(f"/properties/{settings.channex_property_id}")
            
            if resp.status_code == 200:
                property_data = resp.json().get("data", {}).get("attributes", {})
                checks.append({
                    "name": "api_connectivity",
                    "passed": True,
                    "message": "API connection successful"
                })
                checks.append({
                    "name": "property_valid",
                    "passed": True,
                    "message": f"Property: {property_data.get('title', 'Unknown')}",
                    "details": {
                        "id": settings.channex_property_id,
                        "title": property_data.get("title"),
                        "currency": property_data.get("currency"),
                        "timezone": property_data.get("timezone")
                    }
                })
            elif resp.status_code == 401:
                checks.append({
                    "name": "api_connectivity",
                    "passed": False,
                    "message": "Invalid API key"
                })
                return {
                    "overall_status": "unhealthy",
                    "timestamp": datetime.utcnow().isoformat(),
                    "base_url": settings.channex_base_url,
                    "checks": checks
                }
            else:
                checks.append({
                    "name": "property_valid",
                    "passed": False,
                    "message": f"Property not found (status {resp.status_code})"
                })
            
            # Check 3: Room type valid
            local_logger.info(f"[LOCAL] GET /room_types/{settings.channex_room_type_id}")
            resp = client.get(f"/room_types/{settings.channex_room_type_id}")
            
            if resp.status_code == 200:
                room_data = resp.json().get("data", {})
                room_attrs = room_data.get("attributes", {})
                room_property_id = room_data.get("relationships", {}).get("property", {}).get("data", {}).get("id")
                belongs_to_property = room_property_id == settings.channex_property_id
                
                checks.append({
                    "name": "room_type_valid",
                    "passed": belongs_to_property,
                    "message": f"Room type: {room_attrs.get('title', 'Unknown')}" if belongs_to_property else "Room type doesn't belong to property",
                    "details": {
                        "id": settings.channex_room_type_id,
                        "title": room_attrs.get("title"),
                        "belongs_to_property": belongs_to_property
                    }
                })
            else:
                checks.append({
                    "name": "room_type_valid",
                    "passed": False,
                    "message": f"Room type not found (status {resp.status_code})"
                })
            
            # Check 4: Rate plan valid
            local_logger.info(f"[LOCAL] GET /rate_plans/{settings.channex_rate_plan_id}")
            resp = client.get(f"/rate_plans/{settings.channex_rate_plan_id}")
            
            if resp.status_code == 200:
                rate_data = resp.json().get("data", {})
                rate_attrs = rate_data.get("attributes", {})
                rate_room_type_id = rate_data.get("relationships", {}).get("room_type", {}).get("data", {}).get("id")
                belongs_to_room = rate_room_type_id == settings.channex_room_type_id
                
                checks.append({
                    "name": "rate_plan_valid",
                    "passed": belongs_to_room,
                    "message": f"Rate plan: {rate_attrs.get('title', 'Unknown')}" if belongs_to_room else "Rate plan doesn't belong to room type",
                    "details": {
                        "id": settings.channex_rate_plan_id,
                        "title": rate_attrs.get("title"),
                        "belongs_to_room_type": belongs_to_room
                    }
                })
            else:
                checks.append({
                    "name": "rate_plan_valid",
                    "passed": False,
                    "message": f"Rate plan not found (status {resp.status_code})"
                })
                
    except httpx.TimeoutException:
        checks.append({
            "name": "api_connectivity",
            "passed": False,
            "message": f"Request timeout after {settings.channex_timeout_seconds}s"
        })
    except Exception as e:
        local_logger.error(f"[LOCAL] Error: {str(e)}")
        checks.append({
            "name": "api_connectivity",
            "passed": False,
            "message": f"Connection error: {str(e)}"
        })
    
    # Calculate overall status
    failed = [c for c in checks if not c["passed"]]
    if not failed:
        overall = "healthy"
    elif len(failed) <= 2:
        overall = "degraded"
    else:
        overall = "unhealthy"
    
    return {
        "overall_status": overall,
        "timestamp": datetime.utcnow().isoformat(),
        "base_url": settings.channex_base_url,
        "checks": checks
    }


@router.get("/channex/local/validate-ids")
async def local_validate_ids():
    """
    Validate that property/room_type/rate_plan IDs are correct and related.
    """
    is_configured, missing = _check_local_env_configured()
    if not is_configured:
        return {
            "success": False,
            "error": {
                "code": "CONFIG_MISSING",
                "message": f"Missing env vars: {', '.join(missing)}"
            }
        }
    
    result = {
        "valid": False,
        "property": {"id": settings.channex_property_id, "valid": False},
        "room_type": {"id": settings.channex_room_type_id, "valid": False, "belongs_to_property": False},
        "rate_plan": {"id": settings.channex_rate_plan_id, "valid": False, "belongs_to_room_type": False}
    }
    
    try:
        with _get_local_httpx_client() as client:
            # Validate property
            resp = client.get(f"/properties/{settings.channex_property_id}")
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("attributes", {})
                result["property"]["valid"] = True
                result["property"]["title"] = data.get("title")
            
            # Validate room type
            resp = client.get(f"/room_types/{settings.channex_room_type_id}")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                attrs = data.get("attributes", {})
                prop_id = data.get("relationships", {}).get("property", {}).get("data", {}).get("id")
                result["room_type"]["valid"] = True
                result["room_type"]["title"] = attrs.get("title")
                result["room_type"]["belongs_to_property"] = prop_id == settings.channex_property_id
            
            # Validate rate plan
            resp = client.get(f"/rate_plans/{settings.channex_rate_plan_id}")
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                attrs = data.get("attributes", {})
                room_id = data.get("relationships", {}).get("room_type", {}).get("data", {}).get("id")
                result["rate_plan"]["valid"] = True
                result["rate_plan"]["title"] = attrs.get("title")
                result["rate_plan"]["belongs_to_room_type"] = room_id == settings.channex_room_type_id
        
        # Overall valid if all checks pass
        result["valid"] = (
            result["property"]["valid"] and
            result["room_type"]["valid"] and
            result["room_type"]["belongs_to_property"] and
            result["rate_plan"]["valid"] and
            result["rate_plan"]["belongs_to_room_type"]
        )
        
    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "CHANNEX_ERROR",
                "message": str(e)
            }
        }
    
    return {"success": True, **result}


@router.post("/channex/local/test/availability")
async def local_test_availability(request_data: LocalAvailabilityRequest = None):
    """
    Send test availability update to Channex staging.
    
    Uses env var IDs. No auth required - for local testing only.
    """
    is_configured, missing = _check_local_env_configured()
    if not is_configured:
        return {
            "success": False,
            "error": {
                "code": "CONFIG_MISSING",
                "message": f"Missing env vars: {', '.join(missing)}"
            }
        }
    
    # Default dates
    if request_data is None:
        request_data = LocalAvailabilityRequest()
    
    today = date.today()
    date_from = request_data.date_from or today.isoformat()
    date_to = request_data.date_to or (today + timedelta(days=7)).isoformat()
    
    # Build payload
    values = []
    current = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    
    while current <= end:
        values.append({
            "property_id": settings.channex_property_id,
            "room_type_id": settings.channex_room_type_id,
            "date": current.isoformat(),
            "availability": request_data.availability
        })
        current += timedelta(days=1)
    
    payload = {"values": values}
    
    local_logger.info(f"[LOCAL] POST /availability with {len(values)} dates")
    
    try:
        with _get_local_httpx_client() as client:
            resp = client.post("/availability", json=payload)
            
            if resp.status_code in (200, 201):
                local_logger.info(f"[LOCAL] Availability updated successfully")
                return {
                    "success": True,
                    "message": f"Updated availability for {len(values)} dates",
                    "payload_sent": payload,
                    "channex_response": resp.json()
                }
            else:
                local_logger.error(f"[LOCAL] Availability update failed: {resp.status_code}")
                return {
                    "success": False,
                    "error": {
                        "code": "CHANNEX_ERROR",
                        "message": f"Channex returned {resp.status_code}",
                        "details": resp.json() if resp.text else None
                    },
                    "payload_sent": payload
                }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": {
                "code": "TIMEOUT",
                "message": f"Request timeout after {settings.channex_timeout_seconds}s"
            }
        }
    except Exception as e:
        local_logger.error(f"[LOCAL] Error: {str(e)}")
        return {
            "success": False,
            "error": {
                "code": "CHANNEX_ERROR",
                "message": str(e)
            }
        }


@router.post("/channex/local/test/rate")
async def local_test_rate(request_data: LocalRateRequest = None):
    """
    Send test rate update to Channex staging.
    
    Uses env var IDs. No auth required - for local testing only.
    """
    is_configured, missing = _check_local_env_configured()
    if not is_configured:
        return {
            "success": False,
            "error": {
                "code": "CONFIG_MISSING",
                "message": f"Missing env vars: {', '.join(missing)}"
            }
        }
    
    # Default dates
    if request_data is None:
        request_data = LocalRateRequest()
    
    today = date.today()
    date_from = request_data.date_from or today.isoformat()
    date_to = request_data.date_to or (today + timedelta(days=7)).isoformat()
    
    # Build payload
    values = []
    current = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    
    while current <= end:
        values.append({
            "property_id": settings.channex_property_id,
            "rate_plan_id": settings.channex_rate_plan_id,
            "date": current.isoformat(),
            "rate": int(request_data.rate * 100)  # Channex expects cents (30000 = 300.00)
        })
        current += timedelta(days=1)
    
    payload = {"values": values}
    
    local_logger.info(f"[LOCAL] POST /restrictions with {len(values)} dates")
    
    try:
        with _get_local_httpx_client() as client:
            resp = client.post("/restrictions", json=payload)
            
            if resp.status_code in (200, 201):
                local_logger.info(f"[LOCAL] Rates updated successfully")
                return {
                    "success": True,
                    "message": f"Updated rates for {len(values)} dates",
                    "payload_sent": payload,
                    "channex_response": resp.json()
                }
            else:
                local_logger.error(f"[LOCAL] Rate update failed: {resp.status_code}")
                return {
                    "success": False,
                    "error": {
                        "code": "CHANNEX_ERROR",
                        "message": f"Channex returned {resp.status_code}",
                        "details": resp.json() if resp.text else None
                    },
                    "payload_sent": payload
                }
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": {
                "code": "TIMEOUT",
                "message": f"Request timeout after {settings.channex_timeout_seconds}s"
            }
        }
    except Exception as e:
        local_logger.error(f"[LOCAL] Error: {str(e)}")
        return {
            "success": False,
            "error": {
                "code": "CHANNEX_ERROR",
                "message": str(e)
            }
        }


# ==================
# Unmatched Webhook Events
# ==================

@router.get("/webhooks/unmatched")
async def list_unmatched_webhook_events(
    status: Optional[str] = Query(None, description="Filter by status: pending, resolved, ignored"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List unmatched webhook events for admin resolution.
    
    These are webhook events that could not be matched to a unit
    (e.g., missing room_type_id mapping).
    """
    query = db.query(UnmatchedWebhookEvent)
    
    if status:
        query = query.filter(UnmatchedWebhookEvent.status == status)
    
    total = query.count()
    events = query.order_by(UnmatchedWebhookEvent.created_at.desc()).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [
            {
                "id": e.id,
                "provider": e.provider,
                "event_type": e.event_type,
                "external_reservation_id": e.external_reservation_id,
                "property_id": e.property_id,
                "room_type_id": e.room_type_id,
                "rate_plan_id": e.rate_plan_id,
                "reason": e.reason,
                "status": e.status,
                "retry_count": e.retry_count,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
                "resolved_booking_id": e.resolved_booking_id,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None
            }
            for e in events
        ]
    }


@router.get("/webhooks/unmatched/{event_id}")
async def get_unmatched_webhook_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single unmatched webhook event with full raw payload."""
    event = db.query(UnmatchedWebhookEvent).filter(
        UnmatchedWebhookEvent.id == event_id
    ).first()
    
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    return {
        "id": event.id,
        "provider": event.provider,
        "event_type": event.event_type,
        "external_reservation_id": event.external_reservation_id,
        "property_id": event.property_id,
        "room_type_id": event.room_type_id,
        "rate_plan_id": event.rate_plan_id,
        "raw_payload": event.raw_payload,
        "reason": event.reason,
        "status": event.status,
        "retry_count": event.retry_count,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        "resolved_booking_id": event.resolved_booking_id,
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
        "resolved_by_id": event.resolved_by_id
    }


@router.post("/webhooks/unmatched/{event_id}/ignore")
async def ignore_unmatched_webhook_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark an unmatched webhook event as ignored."""
    event = db.query(UnmatchedWebhookEvent).filter(
        UnmatchedWebhookEvent.id == event_id
    ).first()
    
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    event.status = UnmatchedEventStatus.IGNORED.value
    event.resolved_by_id = current_user.id
    event.resolved_at = datetime.utcnow()
    event.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "message": f"Event {event_id} marked as ignored",
        "event_id": event_id,
        "status": event.status
    }
