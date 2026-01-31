"""
Script to fix orphaned events and resync the mapping
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime
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
        print("=" * 50)
        print("FIXING ORPHANED EVENTS & RESYNCING")
        print("=" * 50)
        
        # 1. Get current connection
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.status == 'active'
        ).first()
        
        if not connection:
            print("❌ No active connection found!")
            return
        
        print(f"\n📡 Active Connection: {connection.id}")
        
        # 2. Delete all events for non-existent connections
        valid_conn_ids = [c.id for c in db.query(ChannelConnection).all()]
        
        deleted_count = db.query(IntegrationOutbox).filter(
            ~IntegrationOutbox.connection_id.in_(valid_conn_ids)
        ).delete(synchronize_session=False)
        
        print(f"🗑️  Deleted {deleted_count} orphaned events")
        
        # 3. Delete failed events
        failed_deleted = db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == OutboxStatus.FAILED.value
        ).delete(synchronize_session=False)
        
        print(f"🗑️  Deleted {failed_deleted} failed events")
        
        # 4. Get the mapping
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.connection_id == connection.id,
            ExternalMapping.is_active == True
        ).first()
        
        if not mapping:
            print("❌ No active mapping found!")
            db.commit()
            return
        
        print(f"\n🔗 Mapping: Unit {mapping.unit_id[:8]}...")
        
        # 5. Queue new price update event
        price_event = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.PRICE_UPDATE.value,
            payload={"unit_id": mapping.unit_id, "days_ahead": settings.channex_sync_days},
            unit_id=mapping.unit_id,
            status=OutboxStatus.PENDING.value,
            next_attempt_at=datetime.utcnow()
        )
        db.add(price_event)
        
        # 6. Queue availability update event  
        avail_event = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.AVAIL_UPDATE.value,
            payload={"unit_id": mapping.unit_id, "days_ahead": settings.channex_sync_days},
            unit_id=mapping.unit_id,
            status=OutboxStatus.PENDING.value,
            next_attempt_at=datetime.utcnow()
        )
        db.add(avail_event)
        
        db.commit()
        
        print("\n✅ Queued new sync events:")
        print("  - price_update")
        print("  - avail_update")
        
        print("\n" + "=" * 50)
        print("Now run: python run_sync.py")
        print("=" * 50)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
