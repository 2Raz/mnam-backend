"""
Script to manually process outbox events
Run this to sync pending mappings with Channex
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.services.outbox_worker import OutboxProcessor

def main():
    db = SessionLocal()
    
    try:
        processor = OutboxProcessor(db)
        
        print("=" * 50)
        print("Processing Outbox Events...")
        print("=" * 50)
        
        # Process batch of pending events
        success_count, failure_count = processor.process_batch(limit=50)
        
        print("\n" + "=" * 50)
        print(f"Results:")
        print(f"  ✅ Success: {success_count}")
        print(f"  ❌ Failed: {failure_count}")
        print("=" * 50)
        
        if failure_count > 0:
            print("\nCheck the integration logs for details on failures.")
        elif success_count > 0:
            print("\nSync completed successfully!")
        else:
            print("\nNo pending events to process.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
