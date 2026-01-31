"""
Script to clean up test/staging data from the database
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.channel_integration import (
    ExternalMapping, 
    ChannelConnection, 
    IntegrationOutbox,
    IntegrationLog
)
from app.models.webhook_event import WebhookEventLog
from app.models.rate_state import PropertyRateState

def main():
    db = SessionLocal()
    
    try:
        print("=" * 50)
        print("CLEANING UP TEST/STAGING DATA")
        print("=" * 50)
        
        # 1. Show current data
        conns = db.query(ChannelConnection).all()
        print(f"\nConnections found: {len(conns)}")
        for c in conns:
            print(f"  - {c.id}: property={c.channex_property_id}, status={c.status}")
        
        mappings = db.query(ExternalMapping).all()
        print(f"\nMappings found: {len(mappings)}")
        for m in mappings:
            print(f"  - {m.id}: unit={m.unit_id}, rate_plan={m.channex_rate_plan_id}")
        
        outbox = db.query(IntegrationOutbox).all()
        print(f"\nOutbox events: {len(outbox)}")
        
        logs = db.query(IntegrationLog).count()
        print(f"Integration logs: {logs}")
        
        webhooks = db.query(WebhookEventLog).count()
        print(f"Webhook logs: {webhooks}")
        
        rate_states = db.query(PropertyRateState).all()
        print(f"Rate states: {len(rate_states)}")
        
        # 2. Delete all test data
        print("\n" + "=" * 50)
        print("DELETING ALL TEST DATA...")
        print("=" * 50)
        
        # Delete in order (respect foreign keys)
        deleted_logs = db.query(IntegrationLog).delete()
        print(f"Deleted {deleted_logs} integration logs")
        
        deleted_webhooks = db.query(WebhookEventLog).delete()
        print(f"Deleted {deleted_webhooks} webhook logs")
        
        deleted_outbox = db.query(IntegrationOutbox).delete()
        print(f"Deleted {deleted_outbox} outbox events")
        
        deleted_mappings = db.query(ExternalMapping).delete()
        print(f"Deleted {deleted_mappings} mappings")
        
        deleted_rate_states = db.query(PropertyRateState).delete()
        print(f"Deleted {deleted_rate_states} rate states")
        
        deleted_conns = db.query(ChannelConnection).delete()
        print(f"Deleted {deleted_conns} connections")
        
        db.commit()
        
        print("\n" + "=" * 50)
        print("CLEANUP COMPLETE!")
        print("=" * 50)
        print("\nThe database is now clean and ready for production.")
        print("You can create new connections via the Dashboard.")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
