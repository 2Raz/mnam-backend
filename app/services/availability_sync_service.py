"""
Availability Sync Service
خدمة مزامنة التوفر مع Channex

المسؤوليات:
1. مزامنة حالة الوحدة مع Channex
2. تحديث التوفر بناءً على الحجوزات
3. معالجة الحالات المختلفة (صيانة، تنظيف، مخفية، محجوزة، متاحة)
"""

from datetime import date, timedelta
from typing import List, Optional, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import logging

logger = logging.getLogger(__name__)


class AvailabilitySyncService:
    """
    خدمة مزامنة التوفر مع Channex
    
    القواعد:
    - صيانة/تنظيف/مخفية: كل الأيام مغلقة
    - محجوزة: أيام الحجوزات + يوم بعد الخروج مغلقة
    - متاحة: فقط أيام الحجوزات النشطة مغلقة
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.days_ahead = 365  # عدد الأيام المستقبلية للمزامنة
        
    def sync_unit_availability(self, unit_id: str) -> Dict:
        """
        مزامنة توفر وحدة معينة مع Channex
        
        Args:
            unit_id: معرف الوحدة
            
        Returns:
            dict: نتيجة المزامنة
        """
        from ..models.unit import Unit
        from ..models.booking import Booking
        from ..models.channel_integration import ExternalMapping, ChannelConnection, ConnectionStatus
        from ..services.channex_client import ChannexClient
        
        # جلب الوحدة
        unit = self.db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            return {"success": False, "error": "الوحدة غير موجودة"}
        
        # حساب الحالة الفعلية (المحسوبة) بناءً على الحجوزات
        from .unit_status_service import get_effective_unit_status
        effective_status, has_bookings = get_effective_unit_status(self.db, unit_id)
        
        logger.info(f"📊 Unit '{unit.unit_name}': Manual status='{unit.status}', Effective status='{effective_status}', Has bookings={has_bookings}")
        
        # جلب الـ mappings النشطة
        mappings = self.db.query(ExternalMapping).join(ChannelConnection).filter(
            and_(
                ExternalMapping.unit_id == unit_id,
                ExternalMapping.is_active == True,
                ChannelConnection.status == ConnectionStatus.ACTIVE.value
            )
        ).all()
        
        if not mappings:
            logger.info(f"No active Channex mappings for unit '{unit.unit_name}'")
            return {"success": True, "message": "لا يوجد ربط مع Channex", "effective_status": effective_status}
        
        # حساب التوفر بناءً على الحالة الفعلية (المحسوبة)
        availability_data = self._calculate_availability_with_effective_status(unit, effective_status)
        
        # إرسال التحديث لكل mapping
        results = []
        for mapping in mappings:
            try:
                client = ChannexClient(
                    api_key=mapping.connection.api_key,
                    channex_property_id=mapping.connection.channex_property_id,
                    connection_id=mapping.connection_id,
                    db=self.db
                )
                
                response = client.update_availability(
                    room_type_id=mapping.channex_room_type_id,
                    availability=availability_data
                )
                
                if response.success:
                    logger.info(f"✅ Synced availability for unit '{unit.unit_name}' to Channex")
                    results.append({"mapping_id": mapping.id, "success": True})
                else:
                    logger.error(f"❌ Failed to sync: {response.error}")
                    results.append({"mapping_id": mapping.id, "success": False, "error": response.error})
                    
            except Exception as e:
                logger.exception(f"Error syncing unit {unit_id}: {e}")
                results.append({"mapping_id": mapping.id, "success": False, "error": str(e)})
        
        return {
            "success": all(r["success"] for r in results),
            "unit_name": unit.unit_name,
            "unit_status": unit.status,
            "results": results
        }
    
    def _calculate_availability(self, unit) -> List[Dict]:
        """
        حساب التوفر بناءً على حالة الوحدة والحجوزات
        
        Returns:
            List[Dict]: قائمة التواريخ مع التوفر
        """
        from ..models.booking import Booking
        
        today = date.today()
        end_date = today + timedelta(days=self.days_ahead)
        
        # إنشاء قاموس للتواريخ (افتراضياً متاحة)
        dates_availability = {}
        current = today
        while current <= end_date:
            dates_availability[current] = {
                "available": True,
                "stop_sell": False,
                "reason": None
            }
            current += timedelta(days=1)
        
        # استخدام الدالة الجديدة التي تأخذ الحالة الفعلية
        return self._calculate_availability_with_effective_status(unit, unit.status)
    
    def _calculate_availability_with_effective_status(self, unit, effective_status: str) -> List[Dict]:
        """
        حساب التوفر بناءً على الحالة الفعلية (المحسوبة) للوحدة
        
        Args:
            unit: كائن الوحدة
            effective_status: الحالة الفعلية المحسوبة (قد تختلف عن unit.status)
        
        Returns:
            List[Dict]: قائمة التواريخ مع التوفر
        """
        from ..models.booking import Booking
        
        today = date.today()
        end_date = today + timedelta(days=self.days_ahead)
        
        # إنشاء قاموس للتواريخ (افتراضياً متاحة)
        dates_availability = {}
        current = today
        while current <= end_date:
            dates_availability[current] = {
                "available": True,
                "stop_sell": False,
                "reason": None
            }
            current += timedelta(days=1)
        
        # ⛔ إذا كانت الحالة الفعلية غير "متاحة" → إغلاق اليوم الحالي فقط
        if effective_status in ["صيانة", "تحتاج تنظيف", "مخفية"]:
            # إغلاق اليوم الحالي فقط - باقي الأيام تبقى مفتوحة
            if today in dates_availability:
                dates_availability[today] = {
                    "available": False,
                    "stop_sell": True,
                    "reason": f"unit_status:{effective_status}"
                }
            logger.info(f"🔒 Unit '{unit.unit_name}' TODAY ONLY BLOCKED (status: {effective_status}) - Tomorrow and beyond remain open")
        
        # حالة "محجوزة" تعتمد على تواريخ الحجوزات الفعلية - يتم معالجتها في القسم الآخر
        if effective_status in ["متاحة", "محجوزة"]:
            # ✅ الوحدة متاحة - نحظر فقط أيام الحجوزات الموجودة
            # جلب الحجوزات النشطة
            active_bookings = self.db.query(Booking).filter(
                and_(
                    Booking.unit_id == unit.id,
                    Booking.is_deleted == False,
                    Booking.check_out_date >= today,
                    Booking.status.in_(["مؤكد", "قيد الإقامة", "pending", "confirmed"])
                )
            ).all()
            
            # حظر أيام الحجوزات فقط
            for booking in active_bookings:
                # حظر من يوم الدخول إلى يوم الخروج
                current = booking.check_in_date
                while current <= booking.check_out_date:
                    if current in dates_availability:
                        dates_availability[current] = {
                            "available": False,
                            "stop_sell": True,
                            "reason": f"booking:{booking.id}"
                        }
                    current += timedelta(days=1)
                
                # حظر يوم واحد بعد الخروج (للتنظيف)
                day_after_checkout = booking.check_out_date + timedelta(days=1)
                if day_after_checkout in dates_availability:
                    dates_availability[day_after_checkout] = {
                        "available": False,
                        "stop_sell": True,
                        "reason": f"post_checkout_buffer:{booking.id}"
                    }
            
            logger.info(f"✅ Unit '{unit.unit_name}' AVAILABLE with {len(active_bookings)} bookings blocked")
        
        # تحويل إلى التنسيق المطلوب لـ Channex
        availability_list = []
        for d, info in dates_availability.items():
            availability_list.append({
                "date": d.strftime("%Y-%m-%d"),
                "availability": 1 if info["available"] else 0,
                "stop_sell": info["stop_sell"]
            })
        
        return availability_list
    
    def sync_booking_availability(self, booking_id: str) -> Dict:
        """
        مزامنة التوفر عند إنشاء/تحديث/إلغاء حجز
        """
        from ..models.booking import Booking
        
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return {"success": False, "error": "الحجز غير موجود"}
        
        return self.sync_unit_availability(booking.unit_id)
    
    def get_availability_summary(self, unit_id: str) -> Dict:
        """
        الحصول على ملخص التوفر لوحدة
        """
        from ..models.unit import Unit
        from ..models.booking import Booking
        
        unit = self.db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            return {"error": "الوحدة غير موجودة"}
        
        today = date.today()
        
        # حساب الأيام المحجوزة
        active_bookings = self.db.query(Booking).filter(
            and_(
                Booking.unit_id == unit_id,
                Booking.check_out_date >= today,
                Booking.status.in_(["مؤكد", "قيد الإقامة", "pending"])
            )
        ).all()
        
        booked_days = 0
        for booking in active_bookings:
            start = max(booking.check_in_date, today)
            end = booking.check_out_date
            booked_days += (end - start).days + 1
        
        # تحديد حالة الإغلاق
        is_fully_blocked = unit.status in ["صيانة", "تحتاج تنظيف", "مخفية"]
        
        return {
            "unit_id": unit_id,
            "unit_name": unit.unit_name,
            "status": unit.status,
            "is_fully_blocked": is_fully_blocked,
            "active_bookings_count": len(active_bookings),
            "booked_days_next_year": booked_days,
            "available_for_booking": unit.status == "متاحة"
        }


def sync_unit_to_channex(db: Session, unit_id: str) -> Dict:
    """
    Helper function لمزامنة وحدة مع Channex
    """
    service = AvailabilitySyncService(db)
    return service.sync_unit_availability(unit_id)


def sync_booking_to_channex(db: Session, booking_id: str) -> Dict:
    """
    Helper function لمزامنة حجز مع Channex
    """
    service = AvailabilitySyncService(db)
    return service.sync_booking_availability(booking_id)
