"""
Test Channex API directly for rates
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
        print("TESTING CHANNEX RATES API DIRECTLY")
        print("=" * 60)
        
        # Get connection
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.status == 'active'
        ).first()
        
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.is_active == True
        ).first()
        
        if not connection or not mapping:
            print("No active connection or mapping!")
            return
        
        api_key = connection.api_key
        property_id = connection.channex_property_id
        rate_plan_id = mapping.channex_rate_plan_id
        
        print(f"\n📡 Property ID: {property_id}")
        print(f"📊 Rate Plan ID: {rate_plan_id}")
        
        base_url = settings.channex_base_url
        print(f"🌐 Base URL: {base_url}")
        
        # Try different payload formats
        print("\n" + "=" * 60)
        print("Test 1: Current format (with property_id in values)")
        print("=" * 60)
        
        payload1 = {
            "values": [
                {
                    "property_id": property_id,
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate": 500.0
                }
            ]
        }
        
        response1 = requests.post(
            f"{base_url}/rates",
            headers={
                "user-api-key": api_key,
                "Content-Type": "application/json"
            },
            json=payload1,
            timeout=30
        )
        
        print(f"Status: {response1.status_code}")
        print(f"Response: {response1.text[:500]}")
        
        # Try without property_id
        print("\n" + "=" * 60)
        print("Test 2: Without property_id in values")
        print("=" * 60)
        
        payload2 = {
            "values": [
                {
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate": 500.0
                }
            ]
        }
        
        response2 = requests.post(
            f"{base_url}/rates",
            headers={
                "user-api-key": api_key,
                "Content-Type": "application/json"
            },
            json=payload2,
            timeout=30
        )
        
        print(f"Status: {response2.status_code}")
        print(f"Response: {response2.text[:500]}")
        
        # Try with "rate_value" instead of "rate"
        print("\n" + "=" * 60)
        print("Test 3: Using 'rate_value' field")
        print("=" * 60)
        
        payload3 = {
            "values": [
                {
                    "property_id": property_id,
                    "rate_plan_id": rate_plan_id,
                    "date": "2026-02-01",
                    "rate_value": 500.0
                }
            ]
        }
        
        response3 = requests.post(
            f"{base_url}/rates",
            headers={
                "user-api-key": api_key,
                "Content-Type": "application/json"
            },
            json=payload3,
            timeout=30
        )
        
        print(f"Status: {response3.status_code}")
        print(f"Response: {response3.text[:500]}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
