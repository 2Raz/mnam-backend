"""
Booking Status Auto-Update Service

يقوم بتحديث حالات الحجوزات تلقائياً بناءً على التواريخ:
- الحجوزات المؤكدة التي وصل تاريخ دخولها → "دخول" (اختياري)
- الحجوزات بحالة "دخول" التي انتهى تاريخ مغادرتها → "خروج" أو "مكتمل"
"""

import logging
from datetime import date, datetime
from typing import Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..models.booking import Booking, BookingStatus
from ..models.unit import Unit

logger = logging.getLogger(__name__)


class BookingStatusUpdater:
    """
    خدمة تحديث حالات الحجوزات تلقائياً.
    
    تعمل كمهمة خلفية تُنفذ بشكل دوري.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def auto_checkout_expired_bookings(self) -> Tuple[int, List[str]]:
        """
        تحديث الحجوزات التي انتهى تاريخ مغادرتها ولم يتم إخراجها.
        
        يغير الحالة من "دخول" إلى "مكتمل" إذا مضى تاريخ المغادرة.
        
        Returns:
            Tuple of (count_updated, list_of_booking_ids)
        """
        today = date.today()
        
        # البحث عن الحجوزات بحالة "دخول" التي انتهى تاريخ مغادرتها
        expired_checkins = self.db.query(Booking).filter(
            and_(
                Booking.status.in_(["دخول", "checked_in"]),
                Booking.check_out_date < today,
                Booking.is_deleted == False
            )
        ).all()
        
        updated_ids = []
        for booking in expired_checkins:
            try:
                old_status = booking.status
                booking.status = "مكتمل"
                booking.updated_at = datetime.utcnow()
                updated_ids.append(booking.id)
                
                logger.info(
                    f"Auto-completed booking {booking.id}: "
                    f"{booking.guest_name} ({booking.check_in_date} - {booking.check_out_date})"
                )
                
                # تحديث حالة الوحدة إلى "تحتاج تنظيف"
                self._mark_unit_needs_cleaning(booking.unit_id)
                
            except Exception as e:
                logger.error(f"Error auto-completing booking {booking.id}: {e}")
        
        if updated_ids:
            self.db.commit()
            logger.info(f"Auto-completed {len(updated_ids)} expired bookings")
        
        return len(updated_ids), updated_ids
    
    def _mark_unit_needs_cleaning(self, unit_id: str):
        """تحديث حالة الوحدة إلى تحتاج تنظيف"""
        try:
            unit = self.db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                # التحقق من وجود حقل status في الوحدة
                if hasattr(unit, 'status'):
                    unit.status = "تحتاج تنظيف"
                    logger.info(f"Unit {unit_id} marked as needs cleaning")
                    # 🆕 مزامنة Channex
                    self._sync_unit_to_channex(unit_id)
        except Exception as e:
            logger.warning(f"Could not update unit status: {e}")
    
    def _sync_unit_to_channex(self, unit_id: str):
        """مزامنة التوفر مع Channex بعد تغير حالة الوحدة تلقائياً"""
        try:
            from .availability_sync_service import sync_unit_to_channex
            result = sync_unit_to_channex(self.db, unit_id)
            if result.get("success"):
                logger.info(f"✅ Synced unit {unit_id} to Channex after auto-update")
            else:
                logger.warning(f"⚠️ Failed to sync unit {unit_id}: {result.get('error')}")
        except Exception as e:
            logger.warning(f"Could not sync unit to Channex: {e}")
    
    
    def get_overdue_confirmed_bookings(self) -> List[Booking]:
        """
        الحصول على الحجوزات المؤكدة التي مضى تاريخ دخولها ولم يتم تسجيل الدخول.
        
        لا يتم تغيير حالتها تلقائياً، ولكن يمكن إرسال تنبيهات للمدير.
        """
        today = date.today()
        
        overdue = self.db.query(Booking).filter(
            and_(
                Booking.status.in_(["مؤكد", "confirmed"]),
                Booking.check_in_date < today,
                Booking.check_out_date >= today,  # لم ينتهِ بعد
                Booking.is_deleted == False
            )
        ).all()
        
        return overdue
    
    def get_no_show_bookings(self) -> List[Booking]:
        """
        الحصول على الحجوزات التي مضى تاريخ مغادرتها ولم يتم تسجيل الدخول إطلاقاً.
        (No-Show bookings)
        """
        today = date.today()
        
        no_shows = self.db.query(Booking).filter(
            and_(
                Booking.status.in_(["مؤكد", "confirmed"]),
                Booking.check_out_date < today,
                Booking.is_deleted == False
            )
        ).all()
        
        return no_shows
    
    def mark_no_shows_as_cancelled(self) -> Tuple[int, List[str]]:
        """
        تحديث الحجوزات No-Show إلى ملغي.
        
        الحجوزات المؤكدة التي انتهى تاريخ مغادرتها دون تسجيل دخول.
        """
        no_shows = self.get_no_show_bookings()
        
        updated_ids = []
        for booking in no_shows:
            try:
                booking.status = "ملغي"
                booking.notes = (booking.notes or "") + f"\n[تلقائي] تم إلغاء الحجز لعدم الحضور - {date.today()}"
                booking.updated_at = datetime.utcnow()
                updated_ids.append(booking.id)
                
                logger.info(
                    f"Auto-cancelled no-show booking {booking.id}: "
                    f"{booking.guest_name} ({booking.check_in_date} - {booking.check_out_date})"
                )
            except Exception as e:
                logger.error(f"Error cancelling no-show booking {booking.id}: {e}")
        
        if updated_ids:
            self.db.commit()
            logger.info(f"Auto-cancelled {len(updated_ids)} no-show bookings")
        
        return len(updated_ids), updated_ids
    
    def run_all_auto_updates(self) -> dict:
        """
        تشغيل جميع التحديثات التلقائية.
        
        Returns:
            Dict with results for each update type
        """
        results = {
            "completed_count": 0,
            "completed_ids": [],
            "no_show_count": 0,
            "no_show_ids": [],
            "overdue_count": 0
        }
        
        try:
            # 1. إكمال الحجوزات المنتهية
            completed_count, completed_ids = self.auto_checkout_expired_bookings()
            results["completed_count"] = completed_count
            results["completed_ids"] = completed_ids
            
            # 2. إلغاء حجوزات No-Show (اختياري - يمكن تعطيله)
            # no_show_count, no_show_ids = self.mark_no_shows_as_cancelled()
            # results["no_show_count"] = no_show_count
            # results["no_show_ids"] = no_show_ids
            
            # 3. حساب الحجوزات المتأخرة (للتنبيه فقط)
            overdue = self.get_overdue_confirmed_bookings()
            results["overdue_count"] = len(overdue)
            
            if results["overdue_count"] > 0:
                logger.warning(
                    f"Found {results['overdue_count']} confirmed bookings with overdue check-in dates"
                )
            
        except Exception as e:
            logger.error(f"Error in auto-update: {e}")
        
        return results
