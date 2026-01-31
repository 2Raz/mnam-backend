"""
Script to update the mapping to use the correct (base) rate plan
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.channel_integration import ExternalMapping, IntegrationOutbox, OutboxStatus

# The correct base rate plan ID
CORRECT_RATE_PLAN_ID = "117d5e5b-174b-4cd8-919b-261023cd3d85"

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("UPDATING MAPPING TO USE BASE RATE PLAN")
        print("=" * 60)
        
        # Get active mapping
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.is_active == True
        ).first()
        
        if not mapping:
            print("❌ No active mapping found!")
            return
        
        print(f"\n📌 Current Mapping:")
        print(f"   Rate Plan ID (OLD): {mapping.channex_rate_plan_id}")
        print(f"   Rate Plan ID (NEW): {CORRECT_RATE_PLAN_ID}")
        
        # Update the mapping
        old_rate_plan = mapping.channex_rate_plan_id
        mapping.channex_rate_plan_id = CORRECT_RATE_PLAN_ID
        mapping.last_price_sync_at = None  # Reset to force resync
        
        # Delete any failed/retrying price update events
        deleted = db.query(IntegrationOutbox).filter(
            IntegrationOutbox.event_type == 'price_update',
            IntegrationOutbox.status.in_([OutboxStatus.FAILED.value, OutboxStatus.RETRYING.value])
        ).delete(synchronize_session=False)
        
        print(f"\n🗑️  Deleted {deleted} old price_update events")
        
        db.commit()
        
        print(f"\n✅ Mapping updated successfully!")
        print(f"   Changed from: {old_rate_plan}")
        print(f"   Changed to:   {CORRECT_RATE_PLAN_ID}")
        
        print("\n" + "=" * 60)
        print("Now run:")
        print("  python fix_sync.py")
        print("  python run_sync.py")
        print("=" * 60)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
