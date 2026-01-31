"""
Script to see actual request payload for failed rate updates
"""
import sys
sys.path.insert(0, '.')
import json

from app.database import SessionLocal
from app.models.channel_integration import IntegrationLog

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("FAILED RATE UPDATE PAYLOADS")
        print("=" * 60)
        
        # Get failed rate updates
        logs = db.query(IntegrationLog).filter(
            IntegrationLog.request_url.contains('/rates'),
            IntegrationLog.success == False
        ).order_by(IntegrationLog.created_at.desc()).limit(3).all()
        
        for log in logs:
            print(f"\n⏱️  {log.created_at}")
            print(f"📍 {log.request_method} {log.request_url}")
            print(f"📶 Response: {log.response_status}")
            print(f"❌ Error: {log.error_message}")
            
            if log.request_payload:
                try:
                    if isinstance(log.request_payload, str):
                        payload = json.loads(log.request_payload)
                    else:
                        payload = log.request_payload
                    
                    values = payload.get("values", [])
                    print(f"\n📦 Payload has {len(values)} rates")
                    
                    # Show first rate
                    if values:
                        first = values[0]
                        print(f"   First rate:")
                        print(f"     property_id: {first.get('property_id')}")
                        print(f"     rate_plan_id: {first.get('rate_plan_id')}")
                        print(f"     date: {first.get('date')}")
                        print(f"     rate: {first.get('rate')}")
                except Exception as e:
                    print(f"   Error parsing payload: {e}")
                    print(f"   Raw: {log.request_payload[:200]}...")
            
            print("\n" + "-" * 40)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
