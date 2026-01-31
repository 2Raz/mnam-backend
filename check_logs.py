"""
Script to check integration logs for errors
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.channel_integration import IntegrationLog

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("RECENT INTEGRATION LOGS (Last 20)")
        print("=" * 60)
        
        logs = db.query(IntegrationLog).order_by(
            IntegrationLog.created_at.desc()
        ).limit(20).all()
        
        for log in logs:
            status = "✅" if log.success else "❌"
            print(f"\n{status} {log.event_type} | {log.request_method} {log.request_url}")
            print(f"   Response: {log.response_status}")
            if log.error_message:
                print(f"   Error: {log.error_message}")
            if log.response_body and not log.success:
                # Show first 500 chars of response body for failed requests
                body = log.response_body[:500] if len(log.response_body) > 500 else log.response_body
                print(f"   Body: {body}")
        
        print("\n" + "=" * 60)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
