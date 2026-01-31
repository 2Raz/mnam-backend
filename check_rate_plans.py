"""
Script to check mapping details and compare with Channex
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.channel_integration import ExternalMapping, ChannelConnection
from app.services.channex_client import ChannexClient

def main():
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("MAPPING & CHANNEX RATE PLAN CHECK")
        print("=" * 60)
        
        # Get active mapping
        mapping = db.query(ExternalMapping).filter(
            ExternalMapping.is_active == True
        ).first()
        
        if not mapping:
            print("❌ No active mapping found!")
            return
        
        print(f"\n📌 Current Mapping:")
        print(f"   Unit ID: {mapping.unit_id}")
        print(f"   Room Type ID: {mapping.channex_room_type_id}")
        print(f"   Rate Plan ID: {mapping.channex_rate_plan_id}")
        
        # Get connection
        connection = db.query(ChannelConnection).filter(
            ChannelConnection.id == mapping.connection_id
        ).first()
        
        if not connection:
            print("❌ Connection not found!")
            return
        
        print(f"\n📡 Connection:")
        print(f"   Property ID: {connection.channex_property_id}")
        
        # Fetch rate plans from Channex
        print(f"\n🔍 Fetching Rate Plans from Channex Staging...")
        
        client = ChannexClient(
            api_key=connection.api_key,
            channex_property_id=connection.channex_property_id,
            db=db
        )
        
        response = client.get_rate_plans()
        
        if not response.success:
            print(f"❌ Failed to fetch rate plans: {response.error}")
            return
        
        rate_plans = response.data.get("data", [])
        print(f"\n✅ Found {len(rate_plans)} rate plans in Channex:")
        
        found_match = False
        for rp in rate_plans:
            rp_id = rp.get("id")
            attrs = rp.get("attributes", {})
            title = attrs.get("title", "Unknown")
            room_type_id = rp.get("relationships", {}).get("room_type", {}).get("data", {}).get("id", "N/A")
            
            match_marker = " ⚠️ USED IN MAPPING!" if rp_id == mapping.channex_rate_plan_id else ""
            room_match = " (ROOM MATCHES)" if room_type_id == mapping.channex_room_type_id else ""
            
            if rp_id == mapping.channex_rate_plan_id:
                found_match = True
            
            print(f"   - {title}")
            print(f"     ID: {rp_id}{match_marker}")
            print(f"     Room Type: {room_type_id}{room_match}")
        
        print("\n" + "=" * 60)
        
        if not found_match:
            print("❌ PROBLEM: Rate Plan ID in mapping NOT FOUND in Channex!")
            print(f"   Mapping uses: {mapping.channex_rate_plan_id}")
            print("\n   You need to update the mapping with a valid Rate Plan ID!")
        else:
            print("✅ Rate Plan ID exists in Channex")
        
        print("=" * 60)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
