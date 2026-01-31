"""
BatchBuilder Service

Builds batched payloads for Channex ARI updates:
- Groups events by channex_property_id
- Compresses date ranges when values are identical
- Splits batches to stay under 10MB payload limit
- Produces deterministic, auditable output
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    OutboxEventType
)
from ..config import settings

import logging
logger = logging.getLogger(__name__)


@dataclass
class RateBatch:
    """Batch of rate updates for a single property"""
    channex_property_id: str
    rate_plan_ids: List[str]
    payload: Dict
    size_bytes: int
    unit_ids: List[str]
    event_ids: List[str]


@dataclass
class AvailabilityBatch:
    """Batch of availability updates for a single property"""
    channex_property_id: str
    room_type_ids: List[str]
    payload: Dict
    size_bytes: int
    unit_ids: List[str]
    event_ids: List[str]


class BatchBuilder:
    """
    Builds optimized batches for Channex ARI updates.
    
    Features:
    - Groups events by property to minimize API calls
    - Compresses consecutive days with same values into date ranges
    - Splits batches to stay under 10MB payload limit
    - Deterministic output for audit purposes
    """
    
    def __init__(self, db: Session, max_payload_bytes: int = None):
        self.db = db
        self.max_payload_bytes = max_payload_bytes or settings.channex_max_payload_bytes
    
    def _get_connection(self, connection_id: str) -> Optional[ChannelConnection]:
        """Get connection by ID"""
        return self.db.query(ChannelConnection).filter(
            ChannelConnection.id == connection_id
        ).first()
    
    def _group_by_property(
        self,
        events: List[IntegrationOutbox]
    ) -> Dict[str, List[IntegrationOutbox]]:
        """
        Group events by their channex_property_id.
        
        Returns: {property_id: [events]}
        """
        groups: Dict[str, List[IntegrationOutbox]] = {}
        connection_cache: Dict[str, ChannelConnection] = {}
        
        for event in events:
            # Get connection (with caching)
            if event.connection_id not in connection_cache:
                connection = self._get_connection(event.connection_id)
                if connection:
                    connection_cache[event.connection_id] = connection
            
            connection = connection_cache.get(event.connection_id)
            if not connection or not connection.channex_property_id:
                logger.warning(f"No connection/property for event {event.id}")
                continue
            
            property_id = connection.channex_property_id
            if property_id not in groups:
                groups[property_id] = []
            groups[property_id].append(event)
        
        return groups
    
    def _compress_date_ranges(self, values: List[Dict]) -> List[Dict]:
        """
        Compress consecutive days with same values into date ranges.
        
        Input: [{"date": "2024-01-01", "rate": 100}, {"date": "2024-01-02", "rate": 100}]
        Output: [{"date_from": "2024-01-01", "date_to": "2024-01-02", "rate": 100}]
        """
        if not values:
            return []
        
        # Sort by date
        sorted_values = sorted(values, key=lambda x: x.get("date", ""))
        
        compressed = []
        current_range = None
        
        for item in sorted_values:
            item_date = item.get("date", "")
            # Get the value key (rate or availability)
            value_key = "rate" if "rate" in item else "availability"
            item_value = item.get(value_key)
            
            if current_range is None:
                # Start new range
                current_range = {
                    "date_from": item_date,
                    "date_to": item_date,
                    value_key: item_value
                }
            elif current_range.get(value_key) == item_value:
                # Check if consecutive day
                try:
                    prev_date = datetime.fromisoformat(current_range["date_to"]).date()
                    curr_date = datetime.fromisoformat(item_date).date()
                    if (curr_date - prev_date).days == 1:
                        # Extend range
                        current_range["date_to"] = item_date
                    else:
                        # Gap in dates, start new range
                        compressed.append(current_range)
                        current_range = {
                            "date_from": item_date,
                            "date_to": item_date,
                            value_key: item_value
                        }
                except (ValueError, TypeError):
                    # Date parse error, start new range
                    compressed.append(current_range)
                    current_range = {
                        "date_from": item_date,
                        "date_to": item_date,
                        value_key: item_value
                    }
            else:
                # Value changed, start new range
                compressed.append(current_range)
                current_range = {
                    "date_from": item_date,
                    "date_to": item_date,
                    value_key: item_value
                }
        
        # Add last range
        if current_range:
            compressed.append(current_range)
        
        return compressed
    
    def _estimate_payload_size(self, payload: Dict) -> int:
        """
        Estimate payload size in bytes.
        Uses JSON serialization for accuracy.
        """
        return len(json.dumps(payload, default=str).encode('utf-8'))
    
    def _split_batch(
        self,
        batch: RateBatch,
        max_bytes: int = None
    ) -> List[RateBatch]:
        """
        Split a batch if it exceeds the size limit.
        
        Returns list of batches, each under max_bytes.
        """
        max_bytes = max_bytes or self.max_payload_bytes
        
        if batch.size_bytes <= max_bytes:
            return [batch]
        
        # Need to split the values
        values = batch.payload.get("values", [])
        if not values:
            return [batch]
        
        # Calculate target chunk size
        num_chunks = (batch.size_bytes // max_bytes) + 1
        chunk_size = len(values) // num_chunks + 1
        
        result = []
        for i in range(0, len(values), chunk_size):
            chunk_values = values[i:i + chunk_size]
            chunk_payload = {"values": chunk_values}
            chunk_size_bytes = self._estimate_payload_size(chunk_payload)
            
            new_batch = RateBatch(
                channex_property_id=batch.channex_property_id,
                rate_plan_ids=batch.rate_plan_ids,
                payload=chunk_payload,
                size_bytes=chunk_size_bytes,
                unit_ids=batch.unit_ids,
                event_ids=batch.event_ids
            )
            result.append(new_batch)
        
        return result
    
    def build_rate_batches(
        self,
        events: List[IntegrationOutbox]
    ) -> List[RateBatch]:
        """
        Build rate update batches from outbox events.
        
        Groups by property, compresses date ranges, splits if needed.
        """
        property_groups = self._group_by_property(events)
        batches = []
        
        for property_id, property_events in property_groups.items():
            # Collect all mappings and values
            all_values = []
            rate_plan_ids = set()
            unit_ids = []
            event_ids = []
            
            for event in property_events:
                event_ids.append(event.id)
                unit_id = event.payload.get("unit_id") if event.payload else None
                if unit_id:
                    unit_ids.append(unit_id)
                
                # Get mapping for this event
                mapping = self.db.query(ExternalMapping).filter(
                    ExternalMapping.connection_id == event.connection_id,
                    ExternalMapping.unit_id == unit_id,
                    ExternalMapping.is_active == True
                ).first()
                
                if mapping and mapping.channex_rate_plan_id:
                    rate_plan_ids.add(mapping.channex_rate_plan_id)
                    
                    # Get values from event payload
                    event_values = event.payload.get("values", []) if event.payload else []
                    for v in event_values:
                        v["rate_plan_id"] = mapping.channex_rate_plan_id
                        all_values.append(v)
            
            if not all_values:
                continue
            
            # Compress date ranges
            compressed = self._compress_date_ranges(all_values)
            
            # Build payload
            payload = {"values": compressed}
            size_bytes = self._estimate_payload_size(payload)
            
            batch = RateBatch(
                channex_property_id=property_id,
                rate_plan_ids=list(rate_plan_ids),
                payload=payload,
                size_bytes=size_bytes,
                unit_ids=unit_ids,
                event_ids=event_ids
            )
            
            # Split if needed
            batches.extend(self._split_batch(batch))
        
        return batches
    
    def build_availability_batches(
        self,
        events: List[IntegrationOutbox]
    ) -> List[AvailabilityBatch]:
        """
        Build availability update batches from outbox events.
        
        Similar to rate batches but uses room_type_id instead of rate_plan_id.
        """
        property_groups = self._group_by_property(events)
        batches = []
        
        for property_id, property_events in property_groups.items():
            all_values = []
            room_type_ids = set()
            unit_ids = []
            event_ids = []
            
            for event in property_events:
                event_ids.append(event.id)
                unit_id = event.payload.get("unit_id") if event.payload else None
                if unit_id:
                    unit_ids.append(unit_id)
                
                mapping = self.db.query(ExternalMapping).filter(
                    ExternalMapping.connection_id == event.connection_id,
                    ExternalMapping.unit_id == unit_id,
                    ExternalMapping.is_active == True
                ).first()
                
                if mapping and mapping.channex_room_type_id:
                    room_type_ids.add(mapping.channex_room_type_id)
                    
                    event_values = event.payload.get("values", []) if event.payload else []
                    for v in event_values:
                        v["room_type_id"] = mapping.channex_room_type_id
                        all_values.append(v)
            
            if not all_values:
                continue
            
            compressed = self._compress_date_ranges(all_values)
            payload = {"values": compressed}
            size_bytes = self._estimate_payload_size(payload)
            
            batch = AvailabilityBatch(
                channex_property_id=property_id,
                room_type_ids=list(room_type_ids),
                payload=payload,
                size_bytes=size_bytes,
                unit_ids=unit_ids,
                event_ids=event_ids
            )
            
            batches.append(batch)
        
        return batches
