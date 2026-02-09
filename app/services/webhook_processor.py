"""
Async Webhook Processor

Handles the async processing pattern for webhooks:
1. Webhook router: validates -> persists raw event -> returns 200 fast
2. Worker: picks up events -> processes via handler -> updates status

This ensures:
- Fast acknowledgment to Channex (avoid timeouts)
- Reliable processing with retries
- Full audit trail
- Idempotency via event_id
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.webhook_event import WebhookEventLog, WebhookEventStatus
from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    InboundIdempotency,
    ConnectionStatus
)
from ..models.booking import Booking, BookingStatus, BookingSource, SourceType
from ..models.customer import Customer
from ..models.unmatched_webhook import UnmatchedWebhookEvent, UnmatchedEventStatus, UnmatchedEventReason
from ..models.booking_revision import BookingRevision
from ..config import settings
from .channex_client import ChannexClient
from .inventory_service import InventoryService

logger = logging.getLogger(__name__)


@dataclass
class WebhookReceiveResult:
    """Result of receiving a webhook (fast path)"""
    success: bool
    event_log_id: Optional[str] = None
    error: Optional[str] = None
    already_processed: bool = False


@dataclass
class WebhookProcessResult:
    """Result of processing a webhook (async path)"""
    success: bool
    action: str  # created, updated, cancelled, skipped, error
    booking_id: Optional[str] = None
    error: Optional[str] = None


class AsyncWebhookReceiver:
    """
    Fast-path webhook receiver.
    
    Responsibilities:
    1. Basic validation (not heavy processing)
    2. Extract event_id for idempotency check
    3. Persist raw event to WebhookEventLog
    4. Return immediately (let worker process)
    """
    
    def __init__(self, db: Session, request_id: Optional[str] = None):
        self.db = db
        self.request_id = request_id or "no-request-id"
    
    def receive(
        self,
        payload: Dict,
        headers: Optional[Dict] = None
    ) -> WebhookReceiveResult:
        """
        Receive and persist a webhook event for async processing.
        
        This is the FAST PATH - do minimal work here!
        """
        try:
            # Extract identifiers from payload
            event_id = (
                payload.get("id") or
                payload.get("event_id") or
                payload.get("webhook_id")
            )
            # Handle multiple event type formats:
            # 1. Combined: "event": "booking.new"
            # 2. Separate: "event": "booking", "event_type": "new"
            event = payload.get("event") or ""
            event_type_field = payload.get("event_type") or ""
            
            # If event already contains dot notation (e.g., "booking.new"), use it directly
            if "." in event:
                event_type = event
            # If event_type is a full format (e.g., "booking.new"), use it
            elif "." in event_type_field:
                event_type = event_type_field
            # Combine event + event_type (e.g., "booking" + "new" → "booking.new")
            elif event and event_type_field:
                event_type = f"{event}.{event_type_field}"
            # Fallback to whatever we have
            else:
                event_type = event or event_type_field or "unknown"
            
            # Extract booking/reservation ID if present
            data = payload.get("data", {})
            external_id = (
                data.get("id") or
                data.get("reservation_id") or
                data.get("booking_id")
            )
            revision_id = data.get("revision_id")
            
            # Quick idempotency check (if we have event_id)
            if event_id:
                existing = self.db.query(WebhookEventLog).filter(
                    and_(
                        WebhookEventLog.provider == "channex",
                        WebhookEventLog.event_id == event_id,
                        WebhookEventLog.status.in_([
                            WebhookEventStatus.PROCESSED.value,
                            WebhookEventStatus.PROCESSING.value
                        ])
                    )
                ).first()
                
                if existing:
                    logger.info(
                        f"[{self.request_id}] Duplicate event {event_id}, skipping"
                    )
                    return WebhookReceiveResult(
                        success=True,
                        already_processed=True,
                        event_log_id=existing.id
                    )
            
            # Persist raw event
            event_log = WebhookEventLog(
                provider="channex",
                event_id=event_id,
                event_type=event_type,
                external_id=external_id,
                revision_id=revision_id,
                payload_json=json.dumps(payload),
                request_headers=json.dumps(headers) if headers else None,
                status=WebhookEventStatus.RECEIVED.value,
                received_at=datetime.utcnow()
            )
            
            self.db.add(event_log)
            self.db.commit()
            self.db.refresh(event_log)
            
            logger.info(
                f"[{self.request_id}] Received webhook {event_type} "
                f"event_id={event_id}, stored as {event_log.id}"
            )
            
            return WebhookReceiveResult(
                success=True,
                event_log_id=event_log.id
            )
            
        except Exception as e:
            logger.error(f"[{self.request_id}] Error receiving webhook: {e}")
            return WebhookReceiveResult(
                success=False,
                error=str(e)
            )


class WebhookProcessor:
    """
    Async webhook processor (worker).
    
    Picks up RECEIVED events from WebhookEventLog and processes them.
    Should be run periodically by a background job.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_pending_events(self, limit: int = 50) -> List[WebhookEventLog]:
        """
        Get events ready for processing.
        
        Uses skip_locked to prevent race conditions between multiple workers
        processing the same event simultaneously.
        """
        from ..utils.db_helpers import is_postgres
        
        query = self.db.query(WebhookEventLog).filter(
            WebhookEventLog.status == WebhookEventStatus.RECEIVED.value
        ).order_by(
            WebhookEventLog.received_at
        )
        
        # ====== Race Condition Prevention ======
        # Use skip_locked to allow multiple workers to pick different events
        # without processing the same event twice
        if is_postgres(self.db):
            query = query.with_for_update(skip_locked=True)
        
        return query.limit(limit).all()
    
    def process_event(self, event: WebhookEventLog) -> WebhookProcessResult:
        """Process a single webhook event"""
        try:
            # Mark as processing
            event.status = WebhookEventStatus.PROCESSING.value
            self.db.commit()
            
            # Parse payload
            payload = json.loads(event.payload_json)
            
            # Use stored event_type, but if it's missing the dot notation,
            # try to derive it from the payload
            event_type = event.event_type
            if not event_type or "." not in event_type:
                # Re-derive from payload using same logic as receive()
                ev = payload.get("event") or ""
                ev_type = payload.get("event_type") or ""
                if "." in ev:
                    event_type = ev
                elif "." in ev_type:
                    event_type = ev_type
                elif ev and ev_type:
                    event_type = f"{ev}.{ev_type}"
                else:
                    event_type = ev or ev_type or event_type or "unknown"
            
            # Route to handler
            if event_type in ("booking.new", "booking_created"):
                result = self._handle_booking_new(payload, event)
            elif event_type in ("booking.modified", "booking_updated"):
                result = self._handle_booking_modified(payload, event)
            elif event_type in ("booking.cancelled", "booking_cancelled"):
                result = self._handle_booking_cancelled(payload, event)
            else:
                # Unknown event type - mark as skipped
                event.status = WebhookEventStatus.SKIPPED.value
                event.processed_at = datetime.utcnow()
                event.result_action = "ignored"
                self.db.commit()
                return WebhookProcessResult(
                    success=True,
                    action="ignored"
                )
            
            # Update event status
            if result.success:
                event.status = WebhookEventStatus.PROCESSED.value
                event.result_action = result.action
                event.result_booking_id = result.booking_id
            else:
                event.status = WebhookEventStatus.FAILED.value
                event.error_message = result.error
            
            event.processed_at = datetime.utcnow()
            self.db.commit()
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing webhook {event.id}: {e}")
            event.status = WebhookEventStatus.FAILED.value
            event.error_message = str(e)[:1000]
            event.processed_at = datetime.utcnow()
            self.db.commit()
            
            return WebhookProcessResult(
                success=False,
                action="error",
                error=str(e)
            )
    
    def _find_connection_by_property(self, property_id: str) -> Optional[ChannelConnection]:
        """Find connection for a Channex property"""
        return self.db.query(ChannelConnection).filter(
            and_(
                ChannelConnection.channex_property_id == property_id,
                ChannelConnection.provider == "channex",
                ChannelConnection.status == ConnectionStatus.ACTIVE.value
            )
        ).first()
    
    def _find_unit_by_room_type(
        self,
        connection_id: str,
        room_type_id: str
    ) -> Optional[str]:
        """Find MNAM unit_id by Channex room type ID"""
        mapping = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection_id,
                ExternalMapping.channex_room_type_id == room_type_id,
                ExternalMapping.is_active == True
            )
        ).first()
        return mapping.unit_id if mapping else None
    
    def _find_unit_by_rate_plan(
        self,
        connection_id: str,
        rate_plan_id: str
    ) -> Optional[str]:
        """
        Fallback: Find MNAM unit_id by Channex rate plan ID.
        
        Per /chandoc Section 7: Agent MUST resolve booking to unit.
        If room_type_id fails, try rate_plan_id.
        """
        if not rate_plan_id:
            return None
        mapping = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection_id,
                ExternalMapping.channex_rate_plan_id == rate_plan_id,
                ExternalMapping.is_active == True
            )
        ).first()
        return mapping.unit_id if mapping else None
    
    def _check_availability_conflict(
        self,
        unit_id: str,
        check_in,
        check_out,
        exclude_reservation_id: Optional[str] = None
    ) -> Optional[Booking]:
        """
        Check if there's a booking conflict for the given unit and dates.
        
        Returns the conflicting booking if found, None otherwise.
        
        Date overlap logic:
        - New booking overlaps if: new_check_in < existing_check_out AND new_check_out > existing_check_in
        """
        from datetime import date as dt_date
        
        # Build query for overlapping bookings
        query = self.db.query(Booking).filter(
            and_(
                Booking.unit_id == unit_id,
                Booking.is_deleted == False,
                # Exclude cancelled bookings
                Booking.status.notin_(['ملغي', 'cancelled', 'canceled']),
                # Date overlap: new_check_in < existing_check_out AND new_check_out > existing_check_in
                Booking.check_in_date < check_out,
                Booking.check_out_date > check_in
            )
        )
        
        # Exclude the current reservation if it's an update (same external ID)
        if exclude_reservation_id:
            query = query.filter(
                or_(
                    Booking.external_reservation_id != exclude_reservation_id,
                    Booking.external_reservation_id.is_(None)
                )
            )
        
        return query.first()
    
    def _validate_booking_data(
        self,
        check_in,
        check_out,
        total_price: Optional[float] = None,
        guest_name: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate booking data for logical errors.
        
        Returns:
            Tuple of (is_valid, error_message, reason_code)
        """
        from datetime import date, timedelta
        
        today = date.today()
        
        # ===== 1. DATE RANGE VALIDATION =====
        if check_out <= check_in:
            return (
                False,
                f"Invalid date range: check-out ({check_out}) must be after check-in ({check_in})",
                UnmatchedEventReason.INVALID_DATE_RANGE.value
            )
        
        # ===== 2. PAST DATES VALIDATION =====
        # Allow bookings that started in the past but haven't ended yet
        if check_out < today:
            return (
                False,
                f"Booking dates are in the past: check-out ({check_out}) is before today ({today})",
                UnmatchedEventReason.DATES_IN_PAST.value
            )
        
        # ===== 3. FUTURE DATE LIMIT =====
        # Don't accept bookings more than 2 years in advance
        max_future_date = today + timedelta(days=730)  # ~2 years
        if check_in > max_future_date:
            return (
                False,
                f"Booking too far in future: check-in ({check_in}) is more than 2 years from today",
                UnmatchedEventReason.DATES_TOO_FAR.value
            )
        
        # ===== 4. DURATION VALIDATION =====
        duration = (check_out - check_in).days
        
        # Minimum 1 night
        if duration < 1:
            return (
                False,
                f"Stay duration too short: {duration} nights (minimum 1 night)",
                UnmatchedEventReason.DURATION_TOO_SHORT.value
            )
        
        # Maximum 365 nights (1 year) - configurable
        max_duration = 365
        if duration > max_duration:
            return (
                False,
                f"Stay duration too long: {duration} nights (maximum {max_duration} nights)",
                UnmatchedEventReason.DURATION_TOO_LONG.value
            )
        
        # ===== 5. PRICE VALIDATION =====
        if total_price is not None:
            try:
                price = float(total_price)
                # Negative price
                if price < 0:
                    return (
                        False,
                        f"Invalid price: {price} (cannot be negative)",
                        UnmatchedEventReason.INVALID_PRICE.value
                    )
                # Unreasonably high price (more than 1 million per night)
                price_per_night = price / duration if duration > 0 else price
                if price_per_night > 1000000:
                    return (
                        False,
                        f"Suspicious price: {price} for {duration} nights ({price_per_night:.2f}/night)",
                        UnmatchedEventReason.INVALID_PRICE.value
                    )
            except (ValueError, TypeError):
                # Could not parse price - allow with warning
                logger.warning(f"Could not parse price: {total_price}")
        
        # All validations passed
        return (True, None, None)
    
    def _save_unmatched_event(
        self,
        payload: Dict,
        event_type: str,
        reason: str,
        property_id: Optional[str] = None,
        room_type_id: Optional[str] = None,
        rate_plan_id: Optional[str] = None,
        reservation_id: Optional[str] = None
    ) -> UnmatchedWebhookEvent:
        """
        Save an unmatched webhook event for admin resolution.
        
        Per /chandoc Section 8: Webhooks must NOT drop events silently.
        """
        unmatched = UnmatchedWebhookEvent(
            provider="channex",
            event_type=event_type,
            external_reservation_id=reservation_id,
            property_id=property_id,
            room_type_id=room_type_id,
            rate_plan_id=rate_plan_id,
            raw_payload=payload,
            reason=reason,
            status=UnmatchedEventStatus.PENDING.value
        )
        self.db.add(unmatched)
        self.db.commit()
        self.db.refresh(unmatched)
        logger.warning(f"Saved unmatched webhook event {unmatched.id}: {reason}")
        return unmatched
    
    def _handle_booking_new(
        self,
        payload: Dict,
        event: WebhookEventLog
    ) -> WebhookProcessResult:
        """Handle a new booking from Channex"""
        data = payload.get("data", {})
        property_id = payload.get("property_id") or data.get("property_id")
        
        # Find connection
        connection = self._find_connection_by_property(property_id)
        if not connection:
            return WebhookProcessResult(
                success=False,
                action="error",
                error=f"No connection for property {property_id}"
            )
        
        # Extract booking data
        reservation_id = data.get("id") or data.get("reservation_id")
        room_type_id = data.get("room_type_id")
        rate_plan_id = data.get("rate_plan_id")
        
        # Find unit - with fallback to rate_plan_id per /chandoc Section 7
        unit_id = self._find_unit_by_room_type(connection.id, room_type_id)
        if not unit_id:
            # Fallback: try rate_plan_id
            unit_id = self._find_unit_by_rate_plan(connection.id, rate_plan_id)
        
        if not unit_id:
            # Save as unmatched event - DO NOT DROP per /chandoc Section 8
            self._save_unmatched_event(
                payload=payload,
                event_type="booking_new",
                reason=UnmatchedEventReason.NO_MAPPING.value,
                property_id=property_id,
                room_type_id=room_type_id,
                rate_plan_id=rate_plan_id,
                reservation_id=reservation_id
            )
            return WebhookProcessResult(
                success=True,  # Return success to prevent retries
                action="unmatched",
                error=f"No mapping for room type {room_type_id} or rate plan {rate_plan_id} - saved for admin resolution"
            )
        
        # Check if booking already exists (upsert logic)
        # Use FOR UPDATE to prevent race conditions
        existing = self.db.query(Booking).filter(
            Booking.external_reservation_id == reservation_id
        ).with_for_update().first()
        
        if existing:
            # Already created - update if needed (upsert pattern)
            return WebhookProcessResult(
                success=True,
                action="skipped",
                booking_id=existing.id
            )
        
        # Extract guest info
        guest = data.get("guest", {}) or data.get("customer", {})
        guest_name = (
            guest.get("name") or
            guest.get("full_name") or
            f"{guest.get('first_name', '')} {guest.get('last_name', '')}".strip() or
            "OTA Guest"
        )
        guest_phone = guest.get("phone")
        guest_email = guest.get("email")
        
        # Parse dates
        check_in = self._parse_date(data.get("arrival_date") or data.get("check_in"))
        check_out = self._parse_date(data.get("departure_date") or data.get("check_out"))
        
        if not check_in or not check_out:
            self._save_unmatched_event(
                payload=payload,
                event_type="booking_new",
                reason=UnmatchedEventReason.MISSING_DATES.value,
                property_id=property_id,
                room_type_id=room_type_id,
                rate_plan_id=rate_plan_id,
                reservation_id=reservation_id
            )
            return WebhookProcessResult(
                success=True,  # Return success to prevent retries
                action="validation_failed",
                error="Missing dates in booking data"
            )
        
        # ===== COMPREHENSIVE BOOKING VALIDATION =====
        total_price = data.get("total_price") or data.get("amount")
        is_valid, error_msg, reason_code = self._validate_booking_data(
            check_in=check_in,
            check_out=check_out,
            total_price=total_price,
            guest_name=guest_name
        )
        
        if not is_valid:
            self._save_unmatched_event(
                payload=payload,
                event_type="booking_new",
                reason=reason_code or UnmatchedEventReason.INVALID_PAYLOAD.value,
                property_id=property_id,
                room_type_id=room_type_id,
                rate_plan_id=rate_plan_id,
                reservation_id=reservation_id
            )
            logger.warning(f"Validation failed for reservation {reservation_id}: {error_msg}")
            return WebhookProcessResult(
                success=True,  # Return success to prevent Channex retries
                action="validation_failed",
                error=error_msg
            )
        
        # ===== CHECK FOR DATE CONFLICTS =====
        # Prevent double bookings by checking if unit is already booked for these dates
        conflict = self._check_availability_conflict(unit_id, check_in, check_out, reservation_id)
        if conflict:
            # Save as unmatched event for admin resolution
            self._save_unmatched_event(
                payload=payload,
                event_type="booking_new",
                reason=UnmatchedEventReason.DATE_CONFLICT.value,
                property_id=property_id,
                room_type_id=room_type_id,
                rate_plan_id=rate_plan_id,
                reservation_id=reservation_id
            )
            logger.warning(
                f"Date conflict for reservation {reservation_id}: "
                f"Unit {unit_id} already booked from {check_in} to {check_out}. "
                f"Conflicting booking: {conflict.id}"
            )
            return WebhookProcessResult(
                success=True,  # Return success to prevent Channex retries
                action="conflict",
                error=f"Date conflict: Unit already booked from {conflict.check_in_date} to {conflict.check_out_date} (Booking ID: {conflict.id})"
            )
        
        # Get or create customer
        customer = self._find_or_create_customer(guest_name, guest_phone, guest_email)
        
        # Determine channel source
        channel = data.get("ota_name") or data.get("channel") or "channex"
        channel_source = self._map_channel_source(channel)
        
        # Build customer snapshot for archival
        customer_snapshot = {
            "name": guest_name,
            "phone": guest_phone,
            "email": guest_email,
            "country": guest.get("country"),
        }
        
        # Extract currency
        currency = data.get("currency", "SAR")
        
        # Get revision_id for tracking
        revision_id = data.get("revision_id")
        
        # Create booking with all new fields
        booking = Booking(
            unit_id=unit_id,
            customer_id=customer.id if customer else None,
            guest_name=guest_name,
            guest_phone=guest_phone,
            guest_email=guest_email,
            check_in_date=check_in,
            check_out_date=check_out,
            total_price=data.get("total_price") or data.get("amount") or 0,
            status=self._map_booking_status(data.get("status")),
            notes=f"OTA Booking via {channel}",
            source_type=SourceType.CHANNEX.value,
            channel_source=channel_source,
            external_reservation_id=reservation_id,
            external_revision_id=revision_id,
            channel_data=json.dumps(data),
            # NEW: Customer snapshot for archival
            customer_snapshot=customer_snapshot,
            # NEW: Currency
            currency=currency,
            # NEW: Revision tracking
            last_applied_revision_id=revision_id,
            last_applied_revision_at=datetime.utcnow()
        )
        
        self.db.add(booking)
        self.db.commit()
        self.db.refresh(booking)
        
        # NEW: Save revision for audit trail
        if revision_id:
            revision = BookingRevision(
                booking_id=booking.id,
                external_booking_id=reservation_id,
                revision_id=revision_id,
                event_type="new",
                payload=data,
                applied=True
            )
            self.db.add(revision)
        
        # NEW: Update inventory calendar
        try:
            inventory_service = InventoryService(self.db)
            inventory_service.mark_dates_booked(
                unit_id=unit_id,
                booking_id=booking.id,
                check_in=check_in,
                check_out=check_out
            )
        except Exception as e:
            logger.error(f"Failed to update inventory calendar: {e}")
        
        # Record idempotency
        self._record_idempotency(
            event.event_id,
            reservation_id,
            revision_id,
            "created",
            booking.id
        )
        
        self.db.commit()
        
        # Queue availability update to Channex
        self._queue_availability_update(connection.id, unit_id)
        
        logger.info(f"Created booking {booking.id} from Channex reservation {reservation_id}")
        
        return WebhookProcessResult(
            success=True,
            action="created",
            booking_id=booking.id
        )
    
    def _handle_booking_modified(
        self,
        payload: Dict,
        event: WebhookEventLog
    ) -> WebhookProcessResult:
        """Handle a modified booking from Channex"""
        data = payload.get("data", {})
        property_id = payload.get("property_id") or data.get("property_id")
        reservation_id = data.get("id") or data.get("reservation_id")
        revision_id = data.get("revision_id")
        
        # Find existing booking with row-level lock for concurrency safety
        booking = self.db.query(Booking).filter(
            Booking.external_reservation_id == reservation_id
        ).with_for_update().first()
        
        if not booking:
            # Booking doesn't exist - upsert by creating it
            logger.info(f"Modified event for unknown booking {reservation_id}, creating new")
            return self._handle_booking_new(payload, event)
        
        # ===== REVISION DEDUP: Check if this revision was already processed =====
        if revision_id:
            existing_revision = self.db.query(BookingRevision).filter(
                BookingRevision.external_booking_id == reservation_id,
                BookingRevision.revision_id == revision_id
            ).first()
            
            if existing_revision:
                logger.info(f"Revision {revision_id} already processed, skipping")
                return WebhookProcessResult(
                    success=True,
                    action="skipped",
                    booking_id=booking.id
                )
        
        # ===== OUT-OF-ORDER PROTECTION =====
        # Compare with last applied revision timestamp
        revision_timestamp = data.get("updated_at") or data.get("timestamp")
        is_out_of_order = False
        
        if booking.last_applied_revision_at and revision_timestamp:
            try:
                new_ts = self._parse_datetime(revision_timestamp)
                if new_ts and new_ts < booking.last_applied_revision_at:
                    logger.warning(
                        f"Out-of-order revision for booking {booking.id}: "
                        f"new_ts={new_ts}, last_applied={booking.last_applied_revision_at}"
                    )
                    is_out_of_order = True
            except Exception:
                pass
        
        # Store old values for inventory diff
        old_check_in = booking.check_in_date
        old_check_out = booking.check_out_date
        old_unit_id = booking.unit_id
        
        # Extract new values
        guest = data.get("guest", {}) or data.get("customer", {})
        new_check_in = self._parse_date(data.get("arrival_date") or data.get("check_in"))
        new_check_out = self._parse_date(data.get("departure_date") or data.get("check_out"))
        
        # ===== SAVE REVISION (even if out-of-order) =====
        if revision_id:
            revision = BookingRevision(
                booking_id=booking.id,
                external_booking_id=reservation_id,
                revision_id=revision_id,
                event_type="modification",
                payload=data,
                applied=not is_out_of_order  # Mark as not applied if out-of-order
            )
            self.db.add(revision)
        
        # If out-of-order, don't apply changes to booking
        if is_out_of_order:
            self.db.commit()
            return WebhookProcessResult(
                success=True,
                action="skipped_out_of_order",
                booking_id=booking.id
            )
        
        # ===== APPLY CHANGES TO BOOKING =====
        if guest.get("name") or guest.get("full_name"):
            booking.guest_name = guest.get("name") or guest.get("full_name")
        if guest.get("phone"):
            booking.guest_phone = guest.get("phone")
        if guest.get("email"):
            booking.guest_email = guest.get("email")
        
        # Update dates
        dates_changed = False
        if new_check_in and new_check_in != booking.check_in_date:
            booking.check_in_date = new_check_in
            dates_changed = True
        if new_check_out and new_check_out != booking.check_out_date:
            booking.check_out_date = new_check_out
            dates_changed = True
        
        if data.get("total_price") or data.get("amount"):
            booking.total_price = data.get("total_price") or data.get("amount")
        
        if data.get("status"):
            booking.status = self._map_booking_status(data.get("status"))
        
        if data.get("currency"):
            booking.currency = data.get("currency")
        
        # Update revision tracking
        booking.external_revision_id = revision_id
        booking.last_applied_revision_id = revision_id
        booking.last_applied_revision_at = datetime.utcnow()
        booking.channel_data = json.dumps(data)
        booking.updated_at = datetime.utcnow()
        
        # ===== INVENTORY DIFF LOGIC =====
        if dates_changed and new_check_in and new_check_out:
            try:
                inventory_service = InventoryService(self.db)
                inventory_service.apply_booking_change(
                    unit_id=booking.unit_id,
                    booking_id=booking.id,
                    old_check_in=old_check_in,
                    old_check_out=old_check_out,
                    new_check_in=new_check_in,
                    new_check_out=new_check_out,
                    old_unit_id=old_unit_id
                )
            except Exception as e:
                logger.error(f"Failed to update inventory calendar for modification: {e}")
        
        self.db.commit()
        
        # Record idempotency
        self._record_idempotency(
            event.event_id,
            reservation_id,
            revision_id,
            "updated",
            booking.id
        )
        
        # Queue availability update if dates changed
        if dates_changed:
            connection = self._find_connection_by_property(property_id)
            if connection:
                self._queue_availability_update(connection.id, booking.unit_id)
        
        logger.info(f"Updated booking {booking.id} from Channex (revision: {revision_id})")
        
        return WebhookProcessResult(
            success=True,
            action="updated",
            booking_id=booking.id
        )
    
    def _handle_booking_cancelled(
        self,
        payload: Dict,
        event: WebhookEventLog
    ) -> WebhookProcessResult:
        """Handle a cancelled booking from Channex"""
        data = payload.get("data", {})
        property_id = payload.get("property_id") or data.get("property_id")
        reservation_id = data.get("id") or data.get("reservation_id")
        
        # Find existing booking
        booking = self.db.query(Booking).filter(
            Booking.external_reservation_id == reservation_id
        ).first()
        
        if not booking:
            # Nothing to cancel
            self._record_idempotency(
                event.event_id,
                reservation_id,
                data.get("revision_id"),
                "not_found",
                None
            )
            return WebhookProcessResult(
                success=True,
                action="not_found"
            )
        
        # Cancel booking
        booking.status = BookingStatus.CANCELLED.value
        revision_id = data.get("revision_id")
        booking.external_revision_id = revision_id
        booking.notes = (booking.notes or "") + f"\nCancelled via Channex on {datetime.utcnow().isoformat()}"
        booking.updated_at = datetime.utcnow()
        
        # Save revision for audit trail
        if revision_id:
            revision = BookingRevision(
                booking_id=booking.id,
                external_booking_id=reservation_id,
                revision_id=revision_id,
                event_type="cancellation",
                payload=data,
                applied=True
            )
            self.db.add(revision)
        
        # FREE INVENTORY CALENDAR
        try:
            inventory_service = InventoryService(self.db)
            inventory_service.apply_cancellation(
                unit_id=booking.unit_id,
                booking_id=booking.id,
                check_in=booking.check_in_date,
                check_out=booking.check_out_date
            )
        except Exception as e:
            logger.error(f"Failed to free inventory calendar for cancellation: {e}")
        
        self.db.commit()
        
        # Record idempotency
        self._record_idempotency(
            event.event_id,
            reservation_id,
            revision_id,
            "cancelled",
            booking.id
        )
        
        # Queue availability update (dates now available)
        connection = self._find_connection_by_property(property_id)
        if connection:
            self._queue_availability_update(connection.id, booking.unit_id)
        
        logger.info(f"Cancelled booking {booking.id} from Channex")
        
        return WebhookProcessResult(
            success=True,
            action="cancelled",
            booking_id=booking.id
        )
    
    def _parse_date(self, date_str: Optional[str]):
        """Parse a date string from Channex"""
        if not date_str:
            return None
        
        from datetime import date as dt_date
        
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str.split("T")[0], fmt.split("T")[0]).date()
            except ValueError:
                continue
        return None
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse a datetime string from Channex"""
        if not dt_str:
            return None
        
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d"
        ):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
    
    def _map_booking_status(self, status: Optional[str]) -> str:
        """Map Channex booking status to MNAM status"""
        if not status:
            return BookingStatus.CONFIRMED.value
        
        status_lower = status.lower()
        if status_lower in ("confirmed", "new", "reserved"):
            return BookingStatus.CONFIRMED.value
        elif status_lower in ("cancelled", "canceled"):
            return BookingStatus.CANCELLED.value
        elif status_lower in ("checked_in", "checkin"):
            return BookingStatus.CHECKED_IN.value
        elif status_lower in ("checked_out", "checkout"):
            return BookingStatus.CHECKED_OUT.value
        elif status_lower == "completed":
            return BookingStatus.COMPLETED.value
        else:
            return BookingStatus.CONFIRMED.value
    
    def _map_channel_source(self, channel: Optional[str]) -> str:
        """Map OTA channel name to BookingSource"""
        if not channel:
            return BookingSource.CHANNEX.value
        
        channel_lower = channel.lower()
        if "airbnb" in channel_lower:
            return BookingSource.AIRBNB.value
        elif "booking.com" in channel_lower or "booking" == channel_lower:
            return BookingSource.BOOKING_COM.value
        elif "expedia" in channel_lower:
            return BookingSource.EXPEDIA.value
        elif "agoda" in channel_lower:
            return BookingSource.AGODA.value
        else:
            return BookingSource.OTHER_OTA.value
    
    def _find_or_create_customer(
        self,
        name: str,
        phone: Optional[str],
        email: Optional[str]
    ) -> Optional[Customer]:
        """Find existing customer or create new one"""
        if not phone and not email:
            return None
        
        # Try to find by phone or email
        if phone:
            customer = self.db.query(Customer).filter(
                Customer.phone == phone
            ).first()
            if customer:
                return customer
        
        if email:
            customer = self.db.query(Customer).filter(
                Customer.email == email
            ).first()
            if customer:
                return customer
        
        # Create new customer
        customer = Customer(
            name=name,
            phone=phone,
            email=email,
            notes="Created from OTA booking"
        )
        self.db.add(customer)
        self.db.flush()
        return customer
    
    def _record_idempotency(
        self,
        event_id: str,
        reservation_id: str,
        revision_id: Optional[str],
        action: str,
        booking_id: Optional[str]
    ):
        """Record that an event was processed for idempotency"""
        record = InboundIdempotency(
            provider="channex",
            external_event_id=event_id or f"no_event_id_{datetime.utcnow().timestamp()}",
            external_reservation_id=reservation_id,
            revision_id=revision_id,
            result_action=action,
            internal_booking_id=booking_id
        )
        self.db.add(record)
        # Commit is done by caller
    
    def _queue_availability_update(self, connection_id: str, unit_id: str):
        """Queue an availability update for the outbox worker"""
        from .outbox_worker import enqueue_availability_update
        enqueue_availability_update(
            db=self.db,
            unit_id=unit_id,
            connection_id=connection_id,
            idempotency_key=f"webhook_avail_{unit_id}_{datetime.utcnow().timestamp()}"
        )
    
    def process_batch(self, limit: int = 50) -> Tuple[int, int]:
        """
        Process a batch of pending webhook events.
        
        Returns (success_count, failure_count)
        """
        events = self.get_pending_events(limit)
        success = 0
        failed = 0
        
        for event in events:
            result = self.process_event(event)
            if result.success:
                success += 1
            else:
                failed += 1
        
        return success, failed
