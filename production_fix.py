"""
Comprehensive fix script for Production sync
1. Clean all old outbox events
2. Reset mapping sync timestamps
3. Create fresh sync events
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, timezone
from app.database import SessionLocal
from app.models.channel_integration import (
    ExternalMapping, 
    ChannelConnection, 
    IntegrationOutbox,
    OutboxEventType,
    OutboxStatus
)
from app.config import settings

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("PRODUCTION SYNC FIX")
        print("=" * 60)
        
        print(f"\n🌐 API URL: {settings.channex_base_url}")
        
        # 1. Get active connection
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.status == 'active'
        ).first()
        
        if not connection:
            print("❌ No active connection!")
            return
        
        print(f"\n📡 Connection: {connection.id}")
        print(f"   Property: {connection.channex_property_id}")
        
        # 2. Get active mapping
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.connection_id == connection.id,
            ExternalMapping.is_active == True
        ).first()
        
        if not mapping:
            print("❌ No active mapping!")
            return
        
        print(f"\n🔗 Mapping: {mapping.id}")
        print(f"   Unit: {mapping.unit_id}")
        print(f"   Room Type: {mapping.channex_room_type_id}")
        print(f"   Rate Plan: {mapping.channex_rate_plan_id}")
        
        # 3. Clean ALL outbox events
        deleted = db.query(IntegrationOutbox).delete(synchronize_session=False)
        print(f"\n🗑️  Deleted {deleted} old outbox events")
        
        # 4. Reset mapping sync timestamps
        mapping.last_price_sync_at = None
        mapping.last_avail_sync_at = None
        print("📝 Reset mapping sync timestamps")
        
        # 5. Create fresh sync events
        now = datetime.now(timezone.utc)
        
        # Full sync event
        full_sync = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.FULL_SYNC.value,
            payload={
                "unit_id": mapping.unit_id, 
                "days_ahead": settings.channex_sync_days
            },
            unit_id=mapping.unit_id,
            status=OutboxStatus.PENDING.value,
            next_attempt_at=now
        )
        db.add(full_sync)
        
        db.commit()
        
        print("\n✅ Created fresh FULL_SYNC event")
        
        print("\n" + "=" * 60)
        print("READY FOR PRODUCTION SYNC!")
        print("=" * 60)
        print("\nRun: python run_sync.py")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
