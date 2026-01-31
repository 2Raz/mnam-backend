"""
Channex Integration Service

Business logic for Channex integration:
- Connect: Validate API key, store connection, fetch property info
- Sync: Pull room types & rate plans, create mappings, push initial ARI
- Mapping: Handle unit <-> room type <-> rate plan relationships

MNAM is the Source of Truth (SoT):
- Prices come from MNAM pricing engine
- Availability is calculated from MNAM bookings
- Channex receives updates, not the other way around
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    ConnectionStatus,
    OutboxEventType,
    OutboxStatus
)
from ..models.project import Project
from ..models.unit import Unit
from ..models.booking import Booking, BookingStatus
from ..config import settings
from .channex_client import ChannexClient, get_channex_client, ChannexResponse
from .pricing_engine import PricingEngine

logger = logging.getLogger(__name__)


@dataclass
class ConnectResult:
    """Result of connecting to Channex"""
    success: bool
    connection_id: Optional[str] = None
    property_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SyncResult:
    """Result of syncing with Channex"""
    success: bool
    room_types_found: int = 0
    rate_plans_found: int = 0
    mappings_created: int = 0
    events_queued: int = 0
    error: Optional[str] = None


@dataclass
class ChannexPropertyInfo:
    """Info about a Channex property"""
    id: str
    title: str
    currency: Optional[str] = None
    timezone: Optional[str] = None
    state_length: Optional[int] = None  # Days of availability data


class ChannexIntegrationService:
    """
    Service layer for Channex integration operations.
    
    Responsibilities:
    - Validate and store connections
    - Fetch and map Channex entities (properties, room types, rate plans)
    - Queue ARI updates for outbox worker
    """
    
    def __init__(self, db: Session, request_id: Optional[str] = None):
        self.db = db
        self.request_id = request_id or "no-request-id"
        self.pricing_engine = PricingEngine(db)
    
    # ==================
    # Connection Management
    # ==================
    
    def connect(
        self,
        project_id: str,
        api_key: str,
        channex_property_id: str,
        webhook_secret: Optional[str] = None,
        created_by_id: Optional[str] = None
    ) -> ConnectResult:
        """
        Connect a MNAM project to a Channex property.
        
        Steps:
        1. Verify project exists
        2. Check no existing connection for this project
        3. Validate API key by calling Channex GET /properties/{id}
        4. Store connection with ACTIVE status
        
        Returns ConnectResult with connection_id on success.
        """
        # 1. Verify project exists
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return ConnectResult(success=False, error="المشروع غير موجود")
        
        # 2. Check no existing connection
        existing = self.db.query(ChannelConnection).filter(
            and_(
                ChannelConnection.project_id == project_id,
                ChannelConnection.provider == "channex"
            )
        ).first()
        
        if existing:
            return ConnectResult(
                success=False,
                error="يوجد اتصال بالفعل لهذا المشروع"
            )
        
        # 3. Validate by calling Channex
        client = ChannexClient(
            api_key=api_key,
            channex_property_id=channex_property_id,
            db=self.db,
            request_id=self.request_id
        )
        
        response = client.get_property(channex_property_id)
        
        if not response.success:
            error_msg = f"فشل التحقق من Channex: {response.error}"
            if response.status_code == 401:
                error_msg = "مفتاح API غير صالح"
            elif response.status_code == 404:
                error_msg = "العقار غير موجود في Channex"
            
            return ConnectResult(success=False, error=error_msg)
        
        # Extract property info
        property_data = response.data.get("data", {}).get("attributes", {}) or response.data
        property_name = property_data.get("title") or property_data.get("name", "Unknown")
        
        # 4. Store connection
        connection = ChannelConnection(
            project_id=project_id,
            provider="channex",
            api_key=api_key,
            channex_property_id=channex_property_id,
            webhook_secret=webhook_secret or settings.channex_webhook_secret,
            status=ConnectionStatus.ACTIVE.value,
            created_by_id=created_by_id,
            last_sync_at=datetime.utcnow()
        )
        
        self.db.add(connection)
        self.db.commit()
        self.db.refresh(connection)
        
        logger.info(
            f"[{self.request_id}] Connected project {project_id} to "
            f"Channex property {channex_property_id} ({property_name})"
        )
        
        return ConnectResult(
            success=True,
            connection_id=connection.id,
            property_name=property_name
        )
    
    def disconnect(self, connection_id: str) -> bool:
        """
        Disconnect a Channex connection.
        
        This will:
        1. Delete all mappings
        2. Cancel pending outbox events
        3. Delete the connection
        """
        connection = self.db.query(ChannelConnection).filter(
            ChannelConnection.id == connection_id
        ).first()
        
        if not connection:
            return False
        
        # Cancel pending outbox events
        self.db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.connection_id == connection_id,
                IntegrationOutbox.status.in_([
                    OutboxStatus.PENDING.value,
                    OutboxStatus.RETRYING.value
                ])
            )
        ).update({"status": OutboxStatus.FAILED.value, "last_error": "Connection deleted"})
        
        # Delete connection (mappings cascade)
        self.db.delete(connection)
        self.db.commit()
        
        logger.info(f"[{self.request_id}] Disconnected connection {connection_id}")
        return True
    
    def get_channex_properties(self, api_key: str) -> Tuple[bool, List[ChannexPropertyInfo]]:
        """
        List all properties accessible with an API key.
        Used for selecting which property to connect.
        """
        logger.info(f"[{self.request_id}] Fetching properties from Channex with API key (length: {len(api_key)})")
        
        client = ChannexClient(
            api_key=api_key,
            channex_property_id="",  # Not needed for listing
            db=self.db,
            request_id=self.request_id
        )
        
        response = client.get_properties()
        
        if not response.success:
            logger.error(
                f"[{self.request_id}] Failed to list properties: "
                f"status={response.status_code}, error={response.error}, "
                f"error_code={response.error_code}"
            )
            return False, []
        
        properties = []
        data = response.data.get("data", []) if response.data else []
        
        logger.info(f"[{self.request_id}] Found {len(data)} properties from Channex")
        
        for item in data:
            attrs = item.get("attributes", {})
            properties.append(ChannexPropertyInfo(
                id=item.get("id"),
                title=attrs.get("title", "Unknown"),
                currency=attrs.get("currency"),
                timezone=attrs.get("timezone"),
                state_length=attrs.get("state_length")
            ))
        
        return True, properties
    
    # ==================
    # Sync Operations
    # ==================
    
    def sync_mappings(
        self,
        connection_id: str,
        auto_map: bool = True
    ) -> SyncResult:
        """
        Sync room types and rate plans from Channex, optionally auto-mapping.
        
        Steps:
        1. Fetch room types from Channex
        2. Fetch rate plans from Channex
        3. If auto_map: match to MNAM units by name or create mappings for first N units
        4. Queue initial ARI sync for each mapping
        """
        connection = self.db.query(ChannelConnection).filter(
            ChannelConnection.id == connection_id
        ).first()
        
        if not connection:
            return SyncResult(success=False, error="الاتصال غير موجود")
        
        client = get_channex_client(connection, self.db, self.request_id)
        
        # 1. Fetch room types
        rt_response = client.get_room_types()
        if not rt_response.success:
            return SyncResult(success=False, error=f"فشل جلب أنواع الغرف: {rt_response.error}")
        
        room_types = rt_response.data.get("data", []) if rt_response.data else []
        
        # 2. Fetch rate plans
        rp_response = client.get_rate_plans()
        if not rp_response.success:
            return SyncResult(success=False, error=f"فشل جلب خطط الأسعار: {rp_response.error}")
        
        rate_plans = rp_response.data.get("data", []) if rp_response.data else []
        
        result = SyncResult(
            success=True,
            room_types_found=len(room_types),
            rate_plans_found=len(rate_plans)
        )
        
        # 3. Auto-map if requested
        if auto_map and room_types:
            mappings_created = self._auto_map_units(
                connection, room_types, rate_plans
            )
            result.mappings_created = mappings_created
        
        # 4. Queue ARI sync for all mappings
        events_queued = self._queue_initial_sync(connection_id)
        result.events_queued = events_queued
        
        # Update last sync time
        connection.last_sync_at = datetime.utcnow()
        self.db.commit()
        
        logger.info(
            f"[{self.request_id}] Synced connection {connection_id}: "
            f"{result.room_types_found} room types, {result.rate_plans_found} rate plans, "
            f"{result.mappings_created} mappings created, {result.events_queued} events queued"
        )
        
        return result
    
    def _auto_map_units(
        self,
        connection: ChannelConnection,
        room_types: List[Dict],
        rate_plans: List[Dict]
    ) -> int:
        """
        Auto-map MNAM units to Channex room types.
        
        Strategy:
        1. Get all units for this project
        2. Match by name if possible
        3. Otherwise, map in order (first unit -> first room type)
        4. For each room type, find the associated rate plan
        """
        # Get project's units
        units = self.db.query(Unit).join(Project).filter(
            Project.id == connection.project_id
        ).all()
        
        if not units:
            logger.warning(f"[{self.request_id}] No units found for project {connection.project_id}")
            return 0
        
        # Build rate plan lookup by room type
        rate_plan_by_room = {}
        for rp in rate_plans:
            room_type_id = rp.get("relationships", {}).get("room_type", {}).get("data", {}).get("id")
            if room_type_id:
                rate_plan_by_room[room_type_id] = rp.get("id")
        
        mappings_created = 0
        
        for i, room_type in enumerate(room_types):
            if i >= len(units):
                break  # No more units to map
            
            room_type_id = room_type.get("id")
            room_name = room_type.get("attributes", {}).get("title", "")
            
            # Find matching unit by name or use index
            unit = None
            for u in units:
                # Check if already mapped
                existing = self.db.query(ExternalMapping).filter(
                    and_(
                        ExternalMapping.connection_id == connection.id,
                        ExternalMapping.unit_id == u.id
                    )
                ).first()
                if existing:
                    continue
                
                # Try name match
                if room_name and room_name.lower() in u.unit_name.lower():
                    unit = u
                    break
            
            # Fallback to first unmapped unit
            if not unit:
                for u in units:
                    existing = self.db.query(ExternalMapping).filter(
                        and_(
                            ExternalMapping.connection_id == connection.id,
                            ExternalMapping.unit_id == u.id
                        )
                    ).first()
                    if not existing:
                        unit = u
                        break
            
            if not unit:
                continue
            
            # Get rate plan for this room type
            rate_plan_id = rate_plan_by_room.get(room_type_id)
            
            if not rate_plan_id:
                logger.warning(
                    f"[{self.request_id}] No rate plan found for room type {room_type_id}"
                )
                continue
            
            # Create mapping
            mapping = ExternalMapping(
                connection_id=connection.id,
                unit_id=unit.id,
                channex_room_type_id=room_type_id,
                channex_rate_plan_id=rate_plan_id,
                mapping_type="unit_to_room",
                is_active=True
            )
            
            self.db.add(mapping)
            mappings_created += 1
            
            logger.info(
                f"[{self.request_id}] Mapped unit {unit.unit_name} -> "
                f"room type {room_name} ({room_type_id})"
            )
        
        self.db.commit()
        return mappings_created
    
    def _queue_initial_sync(self, connection_id: str) -> int:
        """Queue initial ARI sync for all active mappings"""
        mappings = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection_id,
                ExternalMapping.is_active == True
            )
        ).all()
        
        events_queued = 0
        sync_days = settings.channex_sync_days
        
        for mapping in mappings:
            # Queue price update
            price_event = IntegrationOutbox(
                connection_id=connection_id,
                event_type=OutboxEventType.PRICE_UPDATE.value,
                payload={"unit_id": mapping.unit_id, "days_ahead": sync_days},
                unit_id=mapping.unit_id,
                status=OutboxStatus.PENDING.value,
                idempotency_key=f"init_price_{mapping.unit_id}_{datetime.utcnow().date()}"
            )
            self.db.add(price_event)
            
            # Queue availability update
            avail_event = IntegrationOutbox(
                connection_id=connection_id,
                event_type=OutboxEventType.AVAIL_UPDATE.value,
                payload={"unit_id": mapping.unit_id, "days_ahead": sync_days},
                unit_id=mapping.unit_id,
                status=OutboxStatus.PENDING.value,
                idempotency_key=f"init_avail_{mapping.unit_id}_{datetime.utcnow().date()}"
            )
            self.db.add(avail_event)
            
            events_queued += 2
        
        self.db.commit()
        return events_queued
    
    # ==================
    # Manual Mapping
    # ==================
    
    def create_mapping(
        self,
        connection_id: str,
        unit_id: str,
        channex_room_type_id: str,
        channex_rate_plan_id: str
    ) -> Optional[ExternalMapping]:
        """
        Manually create a mapping between a MNAM unit and Channex room type.
        """
        # Verify connection and unit
        connection = self.db.query(ChannelConnection).filter(
            ChannelConnection.id == connection_id
        ).first()
        if not connection:
            return None
        
        unit = self.db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            return None
        
        # Check for existing mapping
        existing = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection_id,
                ExternalMapping.unit_id == unit_id
            )
        ).first()
        
        if existing:
            # Update existing
            existing.channex_room_type_id = channex_room_type_id
            existing.channex_rate_plan_id = channex_rate_plan_id
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
            mapping = existing
        else:
            # Create new
            mapping = ExternalMapping(
                connection_id=connection_id,
                unit_id=unit_id,
                channex_room_type_id=channex_room_type_id,
                channex_rate_plan_id=channex_rate_plan_id,
                mapping_type="unit_to_room",
                is_active=True
            )
            self.db.add(mapping)
        
        self.db.commit()
        self.db.refresh(mapping)
        
        # Queue initial sync for this mapping
        self._queue_sync_for_mapping(connection_id, mapping.unit_id)
        
        return mapping
    
    def _queue_sync_for_mapping(self, connection_id: str, unit_id: str):
        """Queue price and availability sync for a single mapping"""
        sync_days = settings.channex_sync_days
        
        price_event = IntegrationOutbox(
            connection_id=connection_id,
            event_type=OutboxEventType.PRICE_UPDATE.value,
            payload={"unit_id": unit_id, "days_ahead": sync_days},
            unit_id=unit_id,
            status=OutboxStatus.PENDING.value
        )
        self.db.add(price_event)
        
        avail_event = IntegrationOutbox(
            connection_id=connection_id,
            event_type=OutboxEventType.AVAIL_UPDATE.value,
            payload={"unit_id": unit_id, "days_ahead": sync_days},
            unit_id=unit_id,
            status=OutboxStatus.PENDING.value
        )
        self.db.add(avail_event)
        
        self.db.commit()
    
    # ==================
    # Availability Calculation
    # ==================
    
    def calculate_availability(
        self,
        unit_id: str,
        days_ahead: int = 365
    ) -> Dict[date, int]:
        """
        Calculate availability for a unit based on MNAM bookings.
        
        For single-inventory vacation rentals:
        - 1 = available (no booking)
        - 0 = booked
        
        MNAM is the Source of Truth - we calculate from bookings,
        not from any external source.
        """
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        
        # Get all confirmed/checked-in bookings for this unit in the range
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
