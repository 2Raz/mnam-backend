"""
Test Channex API - explore different endpoints
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
        print("EXPLORING CHANNEX API ENDPOINTS")
        print("=" * 60)
        
        # Get connection
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
        
        # Test: List rate plans to confirm they exist
        print("\n🔍 Getting rate plan details...")
        rp_response = requests.get(
            f"{base_url}/rate_plans/{rate_plan_id}",
            headers=headers,
            timeout=30
        )
        print(f"Rate Plan {rate_plan_id}:")
        print(f"  Status: {rp_response.status_code}")
        if rp_response.status_code == 200:
            print(f"  Found: ✅")
            data = rp_response.json()
            print(f"  Data: {json.dumps(data, indent=2)[:500]}")
        else:
            print(f"  Response: {rp_response.text[:200]}")
        
        # Test endpoint variations
        test_payload = {
            "values": [
                {
                    "property_id": property_id,
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate": 500.0
                }
            ]
        }
        
        endpoints = [
            "/rates",
            "/ari/rates",
            "/rate_plans/rates",
            f"/rate_plans/{rate_plan_id}/rates",
            "/values/rates"
        ]
        
        print("\n" + "=" * 60)
        print("Testing different endpoints...")
        print("=" * 60)
        
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            try:
                response = requests.post(url, headers=headers, json=test_payload, timeout=10)
                status = "✅" if response.status_code == 200 else f"❌ {response.status_code}"
                print(f"\n{status} POST {endpoint}")
                if response.status_code != 200:
                    print(f"   {response.text[:100]}")
            except Exception as e:
                print(f"\n⚠️ POST {endpoint}: {e}")
        
        # Check if maybe staging requires different URL
        print("\n" + "=" * 60)
        print("Checking availability endpoint (should work)")
        print("=" * 60)
        
        avail_payload = {
            "values": [
                {
                    "property_id": property_id,
                    "room_type_id": mapping.channex_room_type_id,
                    "date": "2026-02-01",
                    "availability": 1
                }
            ]
        }
        
        avail_response = requests.post(
            f"{base_url}/availability",
            headers=headers,
            json=avail_payload,
            timeout=30
        )
        
        print(f"Status: {avail_response.status_code}")
        print(f"Response: {avail_response.text[:200]}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
