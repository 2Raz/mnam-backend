"""
Enhanced Integration Outbox Worker

Processes outbound events from the IntegrationOutbox table with:
- Token bucket rate limiting per channex_property_id
- Separate buckets for prices vs availability
- Dedup/merge for overlapping events (last-write-wins)
- Exponential backoff with 429 pause handling
- 10MB payload limit enforcement

Features:
- Batching multiple events for efficiency
- Idempotency via idempotency_key
- Status tracking and retry logic
"""

import json
import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    IntegrationLog,
    OutboxStatus,
    OutboxEventType,
    ConnectionStatus
)
from ..models.rate_state import PropertyRateState
from ..models.unit import Unit
from ..models.booking import Booking, BookingStatus
from ..config import settings
from .channex_client import ChannexClient, get_channex_client
from .pricing_engine import PricingEngine
from .batch_builder import BatchBuilder

logger = logging.getLogger(__name__)


class OutboxProcessor:
    """
    Processes events from the IntegrationOutbox with proper rate limiting
    and dedup/merge support.
    
    Should be run periodically by a background task/cron job.
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.pricing_engine = PricingEngine(db)
        self.max_payload_bytes = settings.channex_max_payload_bytes
        self.batch_builder = BatchBuilder(db, self.max_payload_bytes)
    
    def get_pending_events(
        self,
        limit: int = 50,
        connection_id: Optional[str] = None
    ) -> List[IntegrationOutbox]:
        """
        Get events ready for processing.
        
        Returns events that are:
        - PENDING or RETRYING status
        - next_attempt_at <= now
        - attempts < max_attempts
        - connection not paused
        
        Uses skip_locked to prevent race conditions between multiple workers.
        """
        from ..utils.db_helpers import is_postgres
        
        now = datetime.utcnow()
        
        query = self.db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.status.in_([
                    OutboxStatus.PENDING.value,
                    OutboxStatus.RETRYING.value
                ]),
                IntegrationOutbox.next_attempt_at <= now,
                IntegrationOutbox.attempts < IntegrationOutbox.max_attempts
            )
        )
        
        if connection_id:
            query = query.filter(IntegrationOutbox.connection_id == connection_id)
        
        # Order by next_attempt_at to process oldest first
        query = query.order_by(IntegrationOutbox.next_attempt_at)
        
        # ====== Race Condition Prevention ======
        # Use skip_locked to allow multiple workers to process different events
        # without blocking each other or processing the same event twice
        if is_postgres(self.db):
            query = query.with_for_update(skip_locked=True)
        
        return query.limit(limit).all()
    
    def get_failed_events(
        self,
        limit: int = 100,
        connection_id: Optional[str] = None
    ) -> List[IntegrationOutbox]:
        """Get events that have permanently failed"""
        query = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == OutboxStatus.FAILED.value
        )
        
        if connection_id:
            query = query.filter(IntegrationOutbox.connection_id == connection_id)
        
        return query.order_by(IntegrationOutbox.created_at.desc()).limit(limit).all()
    
    def retry_failed_event(self, event_id: str) -> bool:
        """Manually retry a failed event"""
        event = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.id == event_id
        ).first()
        
        if not event:
            return False
        
        event.status = OutboxStatus.PENDING.value
        event.attempts = 0
        event.next_attempt_at = datetime.utcnow()
        event.last_error = None
        self.db.commit()
        return True
    
    def is_property_paused(self, channex_property_id: str) -> bool:
        """Check if a property is paused due to rate limiting"""
        state = self.db.query(PropertyRateState).filter(
            PropertyRateState.channex_property_id == channex_property_id
        ).first()
        
        if not state:
            return False
        
        return state.is_paused()
    
    def merge_overlapping_events(
        self,
        events: List[IntegrationOutbox]
    ) -> List[IntegrationOutbox]:
        """
        Merge overlapping events for the same unit/type.
        
        Last-write-wins: if multiple events for the same unit_id and event_type
        exist, keep only the most recent one.
        """
        # Group by (unit_id, event_type)
        groups: Dict[Tuple[str, str], IntegrationOutbox] = {}
        
        for event in events:
            key = (event.unit_id or "", event.event_type)
            
            if key in groups:
                existing = groups[key]
                # Keep the newer one (by created_at)
                if event.created_at > existing.created_at:
                    # Mark older as completed (merged)
                    existing.status = OutboxStatus.COMPLETED.value
                    existing.last_error = "Merged with newer event"
                    existing.completed_at = datetime.utcnow()
                    groups[key] = event
                else:
                    # Mark this one as completed
                    event.status = OutboxStatus.COMPLETED.value
                    event.last_error = "Merged with newer event"
                    event.completed_at = datetime.utcnow()
            else:
                groups[key] = event
        
        self.db.commit()
        return list(groups.values())
    
    def process_event(self, event: IntegrationOutbox) -> bool:
        """
        Process a single outbox event.
        
        Returns True if successful, False if failed.
        """
        # Mark as processing
        event.status = OutboxStatus.PROCESSING.value
        event.attempts += 1
        self.db.commit()
        
        try:
            # Get connection
            connection = self.db.query(ChannelConnection).filter(
                ChannelConnection.id == event.connection_id
            ).first()
            
            if not connection:
                raise ValueError(f"Connection {event.connection_id} not found")
            
            if connection.status != ConnectionStatus.ACTIVE.value:
                raise ValueError(f"Connection is not active: {connection.status}")
            
            # Check if property is paused
            if self.is_property_paused(connection.channex_property_id):
                # Re-schedule for later
                event.status = OutboxStatus.RETRYING.value
                event.next_attempt_at = datetime.utcnow() + timedelta(seconds=60)
                event.last_error = "Property rate limited, waiting..."
                self.db.commit()
                return False
            
            # Get Channex client with rate limiter
            client = get_channex_client(connection, self.db)
            
            # Process based on event type
            if event.event_type == OutboxEventType.PRICE_UPDATE.value:
                success = self._process_price_update(event, client, connection)
            elif event.event_type == OutboxEventType.AVAIL_UPDATE.value:
                success = self._process_avail_update(event, client, connection)
            elif event.event_type == OutboxEventType.FULL_SYNC.value:
                success = self._process_full_sync(event, client, connection)
            else:
                raise ValueError(f"Unknown event type: {event.event_type}")
            
            if success:
                event.status = OutboxStatus.COMPLETED.value
                event.completed_at = datetime.utcnow()
                connection.last_sync_at = datetime.utcnow()
                connection.error_count = 0
            else:
                self._handle_failure(event, "Processing returned failure")
            
            self.db.commit()
            return success
            
        except Exception as e:
            logger.error(f"Error processing event {event.id}: {e}")
            self._handle_failure(event, str(e))
            self.db.commit()
            return False
    
    def _handle_failure(self, event: IntegrationOutbox, error: str):
        """Handle event processing failure with exponential backoff"""
        event.last_error = error[:1000]
        
        if event.attempts >= event.max_attempts:
            event.status = OutboxStatus.FAILED.value
            logger.error(f"Event {event.id} permanently failed after {event.attempts} attempts")
        else:
            event.status = OutboxStatus.RETRYING.value
            # Exponential backoff: 1, 2, 4, 8, 16 minutes
            delay_minutes = min(2 ** (event.attempts - 1), 60)
            event.next_attempt_at = datetime.utcnow() + timedelta(minutes=delay_minutes)
            logger.warning(f"Event {event.id} will retry in {delay_minutes} minutes")
    
    def _process_price_update(
        self,
        event: IntegrationOutbox,
        client: ChannexClient,
        connection: ChannelConnection
    ) -> bool:
        """Process a PRICE_UPDATE event"""
        payload = event.payload or {}
        unit_id = payload.get("unit_id") or event.unit_id
        
        if not unit_id:
            logger.error("No unit_id in PRICE_UPDATE event")
            return False
        
        # Get mapping
        mapping = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection.id,
                ExternalMapping.unit_id == unit_id,
                ExternalMapping.is_active == True
            )
        ).first()
        
        if not mapping or not mapping.channex_rate_plan_id:
            logger.error(f"No active mapping found for unit {unit_id}")
            return False
        
        # Get prices from pricing engine
        days_ahead = payload.get("days_ahead", settings.channex_sync_days)
        prices = self.pricing_engine.get_prices_for_channel_push(unit_id, days_ahead)
        
        if not prices:
            logger.warning(f"No prices generated for unit {unit_id}")
            return True  # Not an error, just no policy yet
        
        # Format for Channex
        rate_values = [
            {"date": p["date"], "rate": p["rate"]}
            for p in prices
        ]
        
        # Split into chunks to respect payload limit
        chunks = self._split_into_chunks(rate_values, "rate")
        
        for chunk in chunks:
            response = client.update_rates(mapping.channex_rate_plan_id, chunk)
            
            if not response.success:
                logger.error(f"Failed to push rates: {response.error}")
                if response.rate_limited:
                    # Will be retried later due to pause
                    pass
                return False
        
        # Update mapping sync time
        mapping.last_price_sync_at = datetime.utcnow()
        
        event.response_data = {"pushed_days": len(prices)}
        return True
    
    def _process_avail_update(
        self,
        event: IntegrationOutbox,
        client: ChannexClient,
        connection: ChannelConnection
    ) -> bool:
        """Process an AVAIL_UPDATE event"""
        payload = event.payload or {}
        unit_id = payload.get("unit_id") or event.unit_id
        
        if not unit_id:
            logger.error("No unit_id in AVAIL_UPDATE event")
            return False
        
        # Get mapping
        mapping = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection.id,
                ExternalMapping.unit_id == unit_id,
                ExternalMapping.is_active == True
            )
        ).first()
        
        if not mapping or not mapping.channex_room_type_id:
            logger.error(f"No active mapping found for unit {unit_id}")
            return False
        
        # Calculate availability for next N days
        days_ahead = payload.get("days_ahead", settings.channex_sync_days)
        availability = self._calculate_availability(unit_id, days_ahead)
        
        # Format for Channex
        avail_values = [
            {"date": d.isoformat(), "availability": a}
            for d, a in availability.items()
        ]
        
        # Split into chunks to respect payload limit
        chunks = self._split_into_chunks(avail_values, "availability")
        
        for chunk in chunks:
            response = client.update_availability(mapping.channex_room_type_id, chunk)
            
            if not response.success:
                logger.error(f"Failed to push availability: {response.error}")
                if response.rate_limited:
                    # Will be retried later due to pause
                    pass
                return False
        
        # Update mapping sync time
        mapping.last_avail_sync_at = datetime.utcnow()
        
        event.response_data = {"pushed_days": len(availability)}
        return True
    
    def _process_full_sync(
        self,
        event: IntegrationOutbox,
        client: ChannexClient,
        connection: ChannelConnection
    ) -> bool:
        """Process a FULL_SYNC event (prices + availability)"""
        payload = event.payload or {}
        unit_id = payload.get("unit_id") or event.unit_id
        
        # Create sub-events for price and availability
        price_event = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.PRICE_UPDATE.value,
            payload={"unit_id": unit_id, "days_ahead": settings.channex_sync_days},
            unit_id=unit_id,
            status=OutboxStatus.PENDING.value
        )
        
        avail_event = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.AVAIL_UPDATE.value,
            payload={"unit_id": unit_id, "days_ahead": settings.channex_sync_days},
            unit_id=unit_id,
            status=OutboxStatus.PENDING.value
        )
        
        self.db.add_all([price_event, avail_event])
        return True
    
    def _calculate_availability(
        self,
        unit_id: str,
        days_ahead: int = 365
    ) -> Dict[date, int]:
        """
        Calculate availability for a unit.
        
        For single-inventory units, availability is:
        - 1 if no booking overlaps the date
        - 0 if booked
        """
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        
        # Get all confirmed bookings for this unit
        bookings = self.db.query(Booking).filter(
            and_(
                Booking.unit_id == unit_id,
                Booking.status.in_([
                    BookingStatus.CONFIRMED.value,
                    BookingStatus.CHECKED_IN.value
                ]),
                Booking.check_out_date >= today,
                Booking.check_in_date <= end_date
            )
        ).all()
        
        # Build set of booked dates
        booked_dates = set()
        for booking in bookings:
            current = booking.check_in_date
            while current < booking.check_out_date:
                booked_dates.add(current)
                current += timedelta(days=1)
        
        # Generate availability map
        availability = {}
        current_date = today
        while current_date <= end_date:
            availability[current_date] = 0 if current_date in booked_dates else 1
            current_date += timedelta(days=1)
        
        return availability
    
    def _split_into_chunks(
        self,
        values: List[Dict],
        value_key: str
    ) -> List[List[Dict]]:
        """
        Split values into chunks that respect the payload size limit.
        
        Each chunk will be under max_payload_bytes when serialized.
        """
        max_size = self.max_payload_bytes
        chunks = []
        current_chunk = []
        current_size = 0
        
        # Estimate overhead for JSON structure
        wrapper_overhead = 100  # {"values": [...]}
        item_overhead = 50  # {"date": "...", "key": ...}
        
        for item in values:
            # Estimate item size
            item_size = item_overhead + len(str(item.get("date", ""))) + len(str(item.get(value_key, "")))
            
            if current_size + item_size + wrapper_overhead > max_size:
                # Start new chunk
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [item]
                current_size = item_size
            else:
                current_chunk.append(item)
                current_size += item_size
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks if chunks else [[]]
    
    def process_batch(self, limit: int = 50) -> Tuple[int, int]:
        """
        Process a batch of pending events with dedup/merge.
        
        Returns: (success_count, failure_count)
        """
        events = self.get_pending_events(limit)
        
        # Merge overlapping events
        events = self.merge_overlapping_events(events)
        
        success_count = 0
        failure_count = 0
        
        # Group events by connection for better batching
        by_connection = defaultdict(list)
        for event in events:
            by_connection[event.connection_id].append(event)
        
        for connection_id, conn_events in by_connection.items():
            for event in conn_events:
                if self.process_event(event):
                    success_count += 1
                else:
                    failure_count += 1
        
        return success_count, failure_count


# ==================
# Event Enqueueing Functions
# ==================

def enqueue_price_update(
    db: Session,
    unit_id: str,
    connection_id: str,
    days_ahead: int = None,
    idempotency_key: Optional[str] = None
) -> IntegrationOutbox:
    """
    Enqueue a price update for a unit.
    
    Call this when:
    - Pricing policy changes
    - Nightly sync job runs
    """
    if days_ahead is None:
        days_ahead = settings.channex_sync_days
    
    event = IntegrationOutbox(
        connection_id=connection_id,
        event_type=OutboxEventType.PRICE_UPDATE.value,
        payload={"unit_id": unit_id, "days_ahead": days_ahead},
        unit_id=unit_id,
        status=OutboxStatus.PENDING.value,
        idempotency_key=idempotency_key
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def enqueue_availability_update(
    db: Session,
    unit_id: str,
    connection_id: str,
    days_ahead: int = None,
    idempotency_key: Optional[str] = None
) -> IntegrationOutbox:
    """
    Enqueue an availability update for a unit.
    
    Call this when:
    - Booking is created/modified/cancelled
    - Maintenance block is set
    - Nightly sync job runs
    """
    if days_ahead is None:
        days_ahead = settings.channex_sync_days
    
    event = IntegrationOutbox(
        connection_id=connection_id,
        event_type=OutboxEventType.AVAIL_UPDATE.value,
        payload={"unit_id": unit_id, "days_ahead": days_ahead},
        unit_id=unit_id,
        status=OutboxStatus.PENDING.value,
        idempotency_key=idempotency_key
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def enqueue_full_sync(
    db: Session,
    unit_id: str,
    connection_id: str,
    idempotency_key: Optional[str] = None
) -> IntegrationOutbox:
    """
    Enqueue a full sync (prices + availability) for a unit.
    
    Call this when:
    - Unit is first connected to Channex
    - Manual sync is requested
    """
    event = IntegrationOutbox(
        connection_id=connection_id,
        event_type=OutboxEventType.FULL_SYNC.value,
        payload={"unit_id": unit_id},
        unit_id=unit_id,
        status=OutboxStatus.PENDING.value,
        idempotency_key=idempotency_key
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def enqueue_availability_for_booking(
    db: Session,
    booking: Booking
) -> List[IntegrationOutbox]:
    """
    Enqueue availability updates for all channel connections when a booking changes.
    
    This finds all connections for the booking's unit and enqueues updates.
    """
    # Find all connections for this unit
    mappings = db.query(ExternalMapping).join(ChannelConnection).filter(
        and_(
            ExternalMapping.unit_id == booking.unit_id,
            ExternalMapping.is_active == True,
            ChannelConnection.status == ConnectionStatus.ACTIVE.value
        )
    ).all()
    
    events = []
    for mapping in mappings:
        idempotency_key = f"avail_booking_{booking.id}_{mapping.connection_id}_{datetime.utcnow().timestamp()}"
        event = enqueue_availability_update(
            db=db,
            unit_id=booking.unit_id,
            connection_id=mapping.connection_id,
            idempotency_key=idempotency_key
        )
        events.append(event)
    
    return events
