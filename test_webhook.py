"""Test webhook endpoint"""
import requests

url = "http://127.0.0.1:8001/api/integrations/webhooks/channex/bookings"

payload = {
    "event": "booking.new",
    "property_id": "test-prop-123",
    "data": {
        "id": "test-res-001",
        "revision_id": "rev-001",
        "arrival_date": "2026-02-10",
        "departure_date": "2026-02-15",
        "total_price": 1500,
        "guest": {"name": "Test Guest"}
    }
}

try:
    r = requests.post(url, json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.json()}")
except Exception as e:
    print(f"Error: {e}")
