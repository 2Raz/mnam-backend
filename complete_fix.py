"""
COMPLETE FIX: Fetch correct IDs from Channex and fix mapping
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
from app.models.unit import Unit
from app.services.channex_client import ChannexClient
from app.config import settings

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("COMPLETE CHANNEX SETUP & FIX")
        print("=" * 60)
        
        # 1. Get connection
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.status == 'active'
        ).first()
        
        if not connection:
            print("❌ No active connection!")
            return
        
        print(f"\n📡 Connection: {connection.id}")
        print(f"   Property: {connection.channex_property_id}")
        print(f"   API Key: {connection.api_key[:20]}...")
        
        # 2. Create Channex client
        client = ChannexClient(
            api_key=connection.api_key,
            channex_property_id=connection.channex_property_id,
            db=db
        )
        
        # 3. Fetch Room Types from Channex
        print("\n🔍 Fetching Room Types from Channex...")
        rt_response = client.get_room_types()
        
        if not rt_response.success:
            print(f"❌ Failed: {rt_response.error}")
            return
        
        room_types = rt_response.data.get("data", [])
        print(f"   Found {len(room_types)} room types:")
        
        for rt in room_types:
            rt_id = rt.get("id")
            attrs = rt.get("attributes", {})
            title = attrs.get("title", "Unknown")
            print(f"   - {title}: {rt_id}")
        
        if not room_types:
            print("❌ No room types found!")
            return
        
        # 4. Fetch Rate Plans from Channex
        print("\n🔍 Fetching Rate Plans from Channex...")
        rp_response = client.get_rate_plans()
        
        if not rp_response.success:
            print(f"❌ Failed: {rp_response.error}")
            return
        
        rate_plans = rp_response.data.get("data", [])
        print(f"   Found {len(rate_plans)} rate plans:")
        
        for rp in rate_plans:
            rp_id = rp.get("id")
            attrs = rp.get("attributes", {})
            title = attrs.get("title", "Unknown")
            rt_rel = rp.get("relationships", {}).get("room_type", {}).get("data", {})
            rt_id = rt_rel.get("id", "N/A")
            print(f"   - {title}: {rp_id}")
            print(f"     Room Type: {rt_id}")
        
        if not rate_plans:
            print("❌ No rate plans found!")
            return
        
        # 5. Get first unit to map
        unit = db.query(Unit).first()
        
        if not unit:
            print("❌ No units found in database!")
            return
        
        print(f"\n📦 Unit to map: {unit.unit_name} ({unit.id})")
        
        # 6. Select first room type and its rate plan
        first_room_type = room_types[0]
        room_type_id = first_room_type.get("id")
        
        # Find rate plan for this room type
        rate_plan_id = None
        for rp in rate_plans:
            rt_rel = rp.get("relationships", {}).get("room_type", {}).get("data", {})
            if rt_rel.get("id") == room_type_id:
                rate_plan_id = rp.get("id")
                break
        
        if not rate_plan_id:
            print(f"❌ No rate plan found for room type {room_type_id}!")
            return
        
        print(f"\n✅ Selected IDs:")
        print(f"   Room Type: {room_type_id}")
        print(f"   Rate Plan: {rate_plan_id}")
        
        # 7. Delete old mappings for this connection
        deleted = db.query(ExternalMapping).filter(
            ExternalMapping.connection_id == connection.id
        ).delete(synchronize_session=False)
        print(f"\n🗑️  Deleted {deleted} old mappings")
        
        # 8. Delete all outbox events
        deleted_events = db.query(IntegrationOutbox).delete(synchronize_session=False)
        print(f"🗑️  Deleted {deleted_events} old outbox events")
        
        # 9. Create new mapping with correct IDs
        new_mapping = ExternalMapping(
            connection_id=connection.id,
            unit_id=unit.id,
            channex_room_type_id=room_type_id,
            channex_rate_plan_id=rate_plan_id,
            mapping_type="room_rate",
            is_active=True
        )
        db.add(new_mapping)
        db.flush()  # Get the ID
        
        print(f"\n✅ Created new mapping: {new_mapping.id}")
        
        # 10. Create full sync event
        now = datetime.now(timezone.utc)
        sync_event = IntegrationOutbox(
            connection_id=connection.id,
            event_type=OutboxEventType.FULL_SYNC.value,
            payload={"unit_id": unit.id, "days_ahead": settings.channex_sync_days},
            unit_id=unit.id,
            status=OutboxStatus.PENDING.value,
            next_attempt_at=now
        )
        db.add(sync_event)
        
        db.commit()
        
        print("✅ Created FULL_SYNC event")
        
        print("\n" + "=" * 60)
        print("SETUP COMPLETE!")
        print("=" * 60)
        print(f"\nMapping: Unit '{unit.unit_name}' → Room Type {room_type_id}")
        print(f"         Rate Plan: {rate_plan_id}")
        print("\nNow run: python run_sync.py")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
