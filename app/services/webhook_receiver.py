"""
Webhook Receiver

Fast-path webhook handler that:
1. Validates request (secret, size, schema)
2. Stores raw event in database
3. Enqueues for async processing
4. Returns 200 immediately

This ensures Channex doesn't retry and we have reliable processing.
"""

import json
import hashlib
import logging
import secrets
from datetime import datetime
from typing import Optional
from fastapi import HTTPException, Request

from sqlalchemy.orm import Session

from ..models.webhook_event import WebhookEventLog, WebhookEventStatus
from ..models.integration_alert import IntegrationAlert, AlertType, AlertSeverity, AlertStatus

logger = logging.getLogger(__name__)


# Maximum payload size (256KB)
MAX_PAYLOAD_SIZE = 256 * 1024

# Required fields in webhook payload
REQUIRED_FIELDS = ["event", "property_id"]


class WebhookReceiveResult:
    """Result from receiving a webhook."""
    
    def __init__(
        self,
        success: bool,
        event_id: Optional[str] = None,
        message: str = "",
        already_exists: bool = False
    ):
        self.success = success
        self.event_id = event_id
        self.message = message
        self.already_exists = already_exists


class WebhookReceiver:
    """
    Handles the fast path for webhook reception.
    
    Flow:
    1. Verify secret header
    2. Validate payload size and schema
    3. Compute hash for dedup
    4. Store in webhook_event_logs
    5. Return immediately (async processing later)
    """
    
    def __init__(self, db: Session, webhook_secret: Optional[str] = None):
        self.db = db
        self.webhook_secret = webhook_secret
    
    def _compute_hash(self, payload: dict) -> str:
        """Compute SHA256 hash of payload for dedup."""
        # Normalize by sorting keys
        normalized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def verify_secret(self, headers: dict) -> bool:
        """
        Verify webhook secret header.
        Returns True if valid or no secret configured.
        """
        if not self.webhook_secret:
            return True
        
        token = headers.get("X-MNAM-Webhook-Token") or headers.get("x-mnam-webhook-token")
        if not token:
            logger.warning("Missing webhook token header")
            return False
        
        return secrets.compare_digest(token, self.webhook_secret)
    
    def validate_payload(self, payload: dict, content_length: int) -> tuple[bool, str]:
        """
        Validate payload size and required fields.
        Returns (is_valid, error_message)
        """
        # Size check
        if content_length > MAX_PAYLOAD_SIZE:
            return False, f"Payload too large: {content_length} > {MAX_PAYLOAD_SIZE}"
        
        # Required fields
        for field in REQUIRED_FIELDS:
            if field not in payload:
                return False, f"Missing required field: {field}"
        
        return True, ""
    
    def receive_booking(self, payload: dict, headers: dict, content_length: int = 0) -> WebhookReceiveResult:
        """
        Receive a booking webhook event.
        
        Args:
            payload: The webhook JSON payload
            headers: Request headers
            content_length: Size of request body
        
        Returns:
            WebhookReceiveResult with status
        """
        try:
            # 1. Verify secret
            if not self.verify_secret(headers):
                logger.warning("Invalid webhook secret")
                raise HTTPException(status_code=401, detail="Invalid webhook token")
            
            # 2. Validate payload
            is_valid, error = self.validate_payload(payload, content_length)
            if not is_valid:
                logger.warning(f"Invalid payload: {error}")
                raise HTTPException(status_code=400, detail=error)
            
            # 3. Compute hash
            payload_hash = self._compute_hash(payload)
            
            # 4. Check for duplicate by hash
            existing = self.db.query(WebhookEventLog).filter(
                WebhookEventLog.provider == "channex",
                WebhookEventLog.payload_hash == payload_hash,
                WebhookEventLog.status.in_([
                    WebhookEventStatus.PROCESSED.value,
                    WebhookEventStatus.PROCESSING.value
                ])
            ).first()
            
            if existing:
                logger.info(f"Duplicate webhook detected (hash match), event_id: {existing.id}")
                return WebhookReceiveResult(
                    success=True,
                    event_id=existing.id,
                    message="Duplicate event",
                    already_exists=True
                )
            
            # 5. Extract identifiers from payload
            event_type = payload.get("event_type") or payload.get("event", "unknown")
            property_id = payload.get("property_id")
            event_id = payload.get("id") or payload.get("event_id")
            
            # Extract booking/revision IDs from nested payload
            data = payload.get("payload", {}) or payload.get("data", {})
            external_id = data.get("booking_id") or data.get("id")
            revision_id = data.get("revision_id")
            
            # 6. Store event
            event_log = WebhookEventLog(
                provider="channex",
                endpoint_type="bookings",
                property_id=property_id,
                event_id=event_id,
                event_type=event_type,
                external_id=external_id,
                revision_id=revision_id,
                payload_json=json.dumps(payload),
                payload_hash=payload_hash,
                request_headers=json.dumps(dict(headers)),
                status=WebhookEventStatus.RECEIVED.value,
                received_at=datetime.utcnow()
            )
            self.db.add(event_log)
            self.db.commit()
            
            logger.info(f"Received booking webhook: type={event_type}, event_id={event_log.id}")
            
            return WebhookReceiveResult(
                success=True,
                event_id=event_log.id,
                message="Event queued for processing"
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error receiving webhook: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail="Internal error processing webhook")
    
    def receive_health(self, payload: dict, headers: dict, content_length: int = 0) -> WebhookReceiveResult:
        """
        Receive a health/error webhook event.
        Creates an alert instead of queuing for booking processing.
        """
        try:
            # 1. Verify secret
            if not self.verify_secret(headers):
                raise HTTPException(status_code=401, detail="Invalid webhook token")
            
            # 2. Validate payload
            is_valid, error = self.validate_payload(payload, content_length)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error)
            
            # 3. Compute hash
            payload_hash = self._compute_hash(payload)
            
            # 4. Extract details
            event_type = payload.get("event_type") or payload.get("event", "unknown")
            property_id = payload.get("property_id")
            
            # Map event type to alert type
            alert_type_map = {
                "unmapped_room": AlertType.UNMAPPED_ROOM.value,
                "unmapped_rate": AlertType.UNMAPPED_RATE.value,
                "sync_error": AlertType.SYNC_ERROR.value,
                "rate_error": AlertType.RATE_ERROR.value,
                "non_acked": AlertType.NON_ACKED.value,
                "booking_unmapped_room": AlertType.UNMAPPED_ROOM.value,
                "booking_unmapped_rate": AlertType.UNMAPPED_RATE.value,
            }
            
            alert_type = alert_type_map.get(event_type, AlertType.CHANNEL_ERROR.value)
            
            # 5. Store event log
            event_log = WebhookEventLog(
                provider="channex",
                endpoint_type="health",
                property_id=property_id,
                event_type=event_type,
                payload_json=json.dumps(payload),
                payload_hash=payload_hash,
                status=WebhookEventStatus.PROCESSED.value,  # Health events are "processed" immediately
                processed_at=datetime.utcnow(),
                result_action="alert_created"
            )
            self.db.add(event_log)
            
            # 6. Create alert
            message = payload.get("message") or f"Health event: {event_type}"
            
            alert = IntegrationAlert(
                provider="channex",
                property_id=property_id,
                alert_type=alert_type,
                severity=AlertSeverity.MEDIUM.value,
                message=message,
                payload_raw=payload,
                status=AlertStatus.OPEN.value
            )
            self.db.add(alert)
            self.db.commit()
            
            logger.info(f"Created alert from health webhook: type={alert_type}, property={property_id}")
            
            return WebhookReceiveResult(
                success=True,
                event_id=event_log.id,
                message="Alert created"
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error receiving health webhook: {e}")
            self.db.rollback()
            raise HTTPException(status_code=500, detail="Internal error processing webhook")
