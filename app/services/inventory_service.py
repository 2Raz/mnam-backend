"""
Inventory Service

Manages daily availability calendar for units.
Implements diff logic for booking modifications.
"""

import logging
from datetime import date, timedelta
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import and_

from ..models.inventory_calendar import InventoryCalendar
from ..models.booking import Booking

logger = logging.getLogger(__name__)


class InventoryService:
    """
    Service for managing unit inventory/availability calendar.
    
    Key responsibilities:
    - Mark dates as booked/available
    - Apply booking modifications with diff logic
    - Block/unblock dates for maintenance
    - Track sync state for Channex
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def _date_range(self, start: date, end: date) -> Set[date]:
        """Generate set of dates from start (inclusive) to end (exclusive)."""
        dates = set()
        current = start
        while current < end:
            dates.add(current)
            current += timedelta(days=1)
        return dates
    
    def _get_or_create(self, unit_id: str, target_date: date) -> InventoryCalendar:
        """Get or create calendar entry for a date."""
        entry = self.db.query(InventoryCalendar).filter(
            InventoryCalendar.unit_id == unit_id,
            InventoryCalendar.date == target_date
        ).first()
        
        if not entry:
            entry = InventoryCalendar(
                unit_id=unit_id,
                date=target_date,
                is_available=True
            )
            self.db.add(entry)
        
        return entry
    
    def mark_dates_booked(
        self, 
        unit_id: str, 
        booking_id: str, 
        check_in: date, 
        check_out: date
    ) -> int:
        """
        Mark dates as booked for a new booking.
        Returns count of dates marked.
        """
        dates = self._date_range(check_in, check_out)
        count = 0
        
        for d in dates:
            entry = self._get_or_create(unit_id, d)
            entry.is_available = False
            entry.is_blocked = False
            entry.booking_id = booking_id
            entry.sync_pending = True
            count += 1
        
        logger.info(f"Marked {count} dates booked for unit {unit_id}, booking {booking_id}")
        return count
    
    def mark_dates_available(
        self, 
        unit_id: str, 
        check_in: date, 
        check_out: date,
        booking_id: Optional[str] = None
    ) -> int:
        """
        Mark dates as available (release from booking).
        If booking_id provided, only releases dates for that booking.
        Returns count of dates freed.
        """
        dates = list(self._date_range(check_in, check_out))
        
        query = self.db.query(InventoryCalendar).filter(
            InventoryCalendar.unit_id == unit_id,
            InventoryCalendar.date.in_(dates)
        )
        
        if booking_id:
            query = query.filter(InventoryCalendar.booking_id == booking_id)
        
        count = query.update({
            "is_available": True,
            "booking_id": None,
            "sync_pending": True
        }, synchronize_session=False)
        
        logger.info(f"Freed {count} dates for unit {unit_id}")
        return count
    
    def apply_booking_change(
        self,
        unit_id: str,
        booking_id: str,
        old_check_in: Optional[date],
        old_check_out: Optional[date],
        new_check_in: date,
        new_check_out: date,
        old_unit_id: Optional[str] = None
    ) -> dict:
        """
        Apply a booking modification with diff logic.
        
        Handles:
        - Date changes (extend/shrink)
        - Unit changes (move to different unit)
        
        Returns dict with counts of dates_freed, dates_booked.
        """
        result = {"dates_freed": 0, "dates_booked": 0, "unit_changed": False}
        
        # Determine old dates (if any)
        old_dates: Set[date] = set()
        if old_check_in and old_check_out:
            old_dates = self._date_range(old_check_in, old_check_out)
        
        new_dates = self._date_range(new_check_in, new_check_out)
        
        # Check if unit changed
        effective_old_unit = old_unit_id or unit_id
        if effective_old_unit != unit_id:
            result["unit_changed"] = True
            # Free all old dates on old unit
            if old_dates:
                result["dates_freed"] = self.mark_dates_available(
                    effective_old_unit, old_check_in, old_check_out, booking_id
                )
            # Book all new dates on new unit
            result["dates_booked"] = self.mark_dates_booked(
                unit_id, booking_id, new_check_in, new_check_out
            )
        else:
            # Same unit, apply diff
            dates_to_free = old_dates - new_dates
            dates_to_book = new_dates - old_dates
            
            # Free dates no longer in range
            if dates_to_free:
                for d in dates_to_free:
                    entry = self.db.query(InventoryCalendar).filter(
                        InventoryCalendar.unit_id == unit_id,
                        InventoryCalendar.date == d,
                        InventoryCalendar.booking_id == booking_id
                    ).first()
                    if entry:
                        entry.is_available = True
                        entry.booking_id = None
                        entry.sync_pending = True
                        result["dates_freed"] += 1
            
            # Book new dates
            if dates_to_book:
                for d in dates_to_book:
                    entry = self._get_or_create(unit_id, d)
                    entry.is_available = False
                    entry.booking_id = booking_id
                    entry.sync_pending = True
                    result["dates_booked"] += 1
        
        logger.info(
            f"Applied booking change: unit={unit_id}, "
            f"freed={result['dates_freed']}, booked={result['dates_booked']}, "
            f"unit_changed={result['unit_changed']}"
        )
        return result
    
    def apply_cancellation(
        self,
        unit_id: str,
        booking_id: str,
        check_in: date,
        check_out: date
    ) -> int:
        """
        Free dates for a cancelled booking.
        """
        return self.mark_dates_available(unit_id, check_in, check_out, booking_id)
    
    def block_dates(
        self,
        unit_id: str,
        start_date: date,
        end_date: date,
        reason: str = "manual_block"
    ) -> int:
        """
        Block dates for maintenance or owner use.
        Returns count of dates blocked.
        """
        dates = self._date_range(start_date, end_date)
        count = 0
        
        for d in dates:
            entry = self._get_or_create(unit_id, d)
            if entry.is_available:  # Don't override bookings
                entry.is_available = False
                entry.is_blocked = True
                entry.block_reason = reason
                entry.sync_pending = True
                count += 1
        
        logger.info(f"Blocked {count} dates for unit {unit_id}, reason: {reason}")
        return count
    
    def unblock_dates(
        self,
        unit_id: str,
        start_date: date,
        end_date: date
    ) -> int:
        """
        Unblock dates.
        Returns count of dates unblocked.
        """
        dates = list(self._date_range(start_date, end_date))
        
        count = self.db.query(InventoryCalendar).filter(
            InventoryCalendar.unit_id == unit_id,
            InventoryCalendar.date.in_(dates),
            InventoryCalendar.is_blocked == True
        ).update({
            "is_available": True,
            "is_blocked": False,
            "block_reason": None,
            "sync_pending": True
        }, synchronize_session=False)
        
        logger.info(f"Unblocked {count} dates for unit {unit_id}")
        return count
    
    def get_availability(
        self,
        unit_id: str,
        start_date: date,
        end_date: date
    ) -> List[dict]:
        """
        Get availability for a date range.
        Returns list of {date, is_available, is_blocked, booking_id}
        """
        entries = self.db.query(InventoryCalendar).filter(
            InventoryCalendar.unit_id == unit_id,
            InventoryCalendar.date >= start_date,
            InventoryCalendar.date < end_date
        ).order_by(InventoryCalendar.date).all()
        
        # Fill in missing dates as available
        result = []
        current = start_date
        entry_map = {e.date: e for e in entries}
        
        while current < end_date:
            if current in entry_map:
                e = entry_map[current]
                result.append({
                    "date": current.isoformat(),
                    "is_available": e.is_available,
                    "is_blocked": e.is_blocked,
                    "booking_id": e.booking_id
                })
            else:
                result.append({
                    "date": current.isoformat(),
                    "is_available": True,
                    "is_blocked": False,
                    "booking_id": None
                })
            current += timedelta(days=1)
        
        return result
    
    def get_pending_sync(self, limit: int = 100) -> List[InventoryCalendar]:
        """Get calendar entries pending sync to Channex."""
        return self.db.query(InventoryCalendar).filter(
            InventoryCalendar.sync_pending == True
        ).limit(limit).all()
    
    def mark_synced(self, entry_ids: List[str]) -> int:
        """Mark entries as synced."""
        from datetime import datetime
        count = self.db.query(InventoryCalendar).filter(
            InventoryCalendar.id.in_(entry_ids)
        ).update({
            "sync_pending": False,
            "last_synced_at": datetime.utcnow()
        }, synchronize_session=False)
        return count
