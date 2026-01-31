"""
Full debug script to see everything
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.channel_integration import (
    ExternalMapping, 
    ChannelConnection, 
    IntegrationOutbox
)

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("FULL DEBUG")
        print("=" * 60)
        
        # ALL Connections
        print("\n📡 ALL CONNECTIONS:")
        connections = db.query(ChannelConnection).all()
        for c in connections:
            print(f"   ID: {c.id}")
            print(f"   Status: {c.status}")
            print(f"   Property: {c.channex_property_id}")
            print()
        
        # ALL Mappings
        print("\n🔗 ALL MAPPINGS:")
        mappings = db.query(ExternalMapping).all()
        for m in mappings:
            print(f"   ID: {m.id}")
            print(f"   Connection ID: {m.connection_id}")
            print(f"   Unit ID: {m.unit_id}")
            print(f"   Room Type: {m.channex_room_type_id}")
            print(f"   Rate Plan: {m.channex_rate_plan_id}")
            print(f"   Is Active: {m.is_active}")
            print(f"   Price Sync: {m.last_price_sync_at}")
            print(f"   Avail Sync: {m.last_avail_sync_at}")
            print()
        
        # ALL Outbox Events
        print("\n📬 ALL OUTBOX EVENTS:")
        events = db.query(IntegrationOutbox).all()
        for e in events:
            print(f"   ID: {e.id[:8]}... | Type: {e.event_type}")
            print(f"   Connection: {e.connection_id}")
            print(f"   Status: {e.status}")
            print(f"   Next Attempt: {e.next_attempt_at}")
            print(f"   Attempts: {e.attempts}/{e.max_attempts}")
            print()
        
        print("=" * 60)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
