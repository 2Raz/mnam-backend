"""
Test updating rate plan values directly
"""
import sys
sys.path.insert(0, '.')
import requests
import json

from app.database import SessionLocal
from app.models.channel_integration import ChannelConnection, ExternalMapping
from app.config import settings

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("TESTING ALTERNATIVE RATE UPDATE METHODS")
        print("=" * 60)
        
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.status == 'active'
        ).first()
        
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.is_active == True
        ).first()
        
        api_key = connection.api_key
        property_id = connection.channex_property_id
        rate_plan_id = mapping.channex_rate_plan_id
        base_url = settings.channex_base_url
        
        headers = {
            "user-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        # Test 1: Update rate plan with values
        print("\n🔄 Test 1: PUT rate plan with values")
        
        payload1 = {
            "rate_plan": {
                "values": [
                    {"date": "2026-02-01", "rate": 500.0}
                ]
            }
        }
        
        r1 = requests.put(
            f"{base_url}/rate_plans/{rate_plan_id}",
            headers=headers,
            json=payload1,
            timeout=30
        )
        print(f"Status: {r1.status_code}")
        print(f"Response: {r1.text[:300]}")
        
        # Test 2: Restrictions endpoint (might work)
        print("\n🔄 Test 2: POST restrictions (similar to rates)")
        
        payload2 = {
            "values": [
                {
                    "property_id": property_id,
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate": 500.0,
                    "min_stay_arrival": 1
                }
            ]
        }
        
        r2 = requests.post(
            f"{base_url}/restrictions",
            headers=headers,
            json=payload2,
            timeout=30
        )
        print(f"Status: {r2.status_code}")
        print(f"Response: {r2.text[:300]}")
        
        # Test 3: values endpoint
        print("\n🔄 Test 3: POST values (combined ARI)")
        
        payload3 = {
            "values": [
                {
                    "property_id": property_id,
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate": 500.0
                }
            ]
        }
        
        r3 = requests.post(
            f"{base_url}/values",
            headers=headers,
            json=payload3,
            timeout=30
        )
        print(f"Status: {r3.status_code}")
        print(f"Response: {r3.text[:300]}")
        
        # Test 4: Check what endpoints exist
        print("\n🔍 Test 4: Checking API root")
        r4 = requests.get(f"{base_url}", headers=headers, timeout=10)
        print(f"API Root Status: {r4.status_code}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
