"""
Script to check the current state of outbox and mappings
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
        print("=" * 50)
        print("CURRENT STATE")
        print("=" * 50)
        
        # Connections
        connections = db.query(ChannelConnection).all()
        print(f"\n📡 Connections: {len(connections)}")
        for c in connections:
            print(f"  - {c.id[:8]}... | Status: {c.status} | Property: {c.channex_property_id[:12]}...")
        
        # Mappings
        mappings = db.query(ExternalMapping).all()
        print(f"\n🔗 Mappings: {len(mappings)}")
        for m in mappings:
            price_sync = "✅" if m.last_price_sync_at else "❌"
            avail_sync = "✅" if m.last_avail_sync_at else "❌"
            print(f"  - {m.id[:8]}... | Unit: {m.unit_id[:8]}... | Price: {price_sync} Avail: {avail_sync}")
        
        # Outbox events
        all_events = db.query(IntegrationOutbox).all()
        print(f"\n📬 Outbox Events: {len(all_events)}")
        
        # Group by status
        by_status = {}
        for e in all_events:
            by_status.setdefault(e.status, []).append(e)
        
        for status, events in by_status.items():
            print(f"\n  {status.upper()}: {len(events)}")
            for e in events[:5]:  # Show first 5
                print(f"    - {e.event_type} | Unit: {e.unit_id[:8] if e.unit_id else 'N/A'}... | Attempts: {e.attempts}/{e.max_attempts}")
                if e.last_error:
                    print(f"      Error: {e.last_error[:80]}...")
        
        print("\n" + "=" * 50)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
