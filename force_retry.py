"""
Script to force retry any retrying events immediately
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime
from app.database import SessionLocal
from app.models.channel_integration import IntegrationOutbox, OutboxStatus

def main():
    db = SessionLocal()
    
    try:
        print("=" * 50)
        print("FORCE RETRY PENDING/RETRYING EVENTS")
        print("=" * 50)
        
        # Get all retrying/pending events
        events = db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
        ).all()
        
        print(f"\n📬 Found {len(events)} events to retry")
        
        now = datetime.utcnow()
        
        for event in events:
            print(f"   - {event.event_type} | Status: {event.status} | next_attempt: {event.next_attempt_at}")
            event.next_attempt_at = now  # Set to now
            event.status = OutboxStatus.PENDING.value  # Reset to pending
            event.attempts = 0  # Reset attempts
        
        db.commit()
        
        print(f"\n✅ Reset {len(events)} events for immediate processing")
        print("\nNow run: python run_sync.py")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
