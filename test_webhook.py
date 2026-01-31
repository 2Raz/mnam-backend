"""
🧪 Test Webhook - إرسال حجز تجريبي للـ Webhook
شغّل هذا الملف لاختبار استقبال الحجوزات من Channex
"""
import requests
import json
import uuid
from datetime import datetime

# ==========================================
# التكوين - غيّر هذه القيم حسب إعداداتك
# ==========================================
WEBHOOK_URL = "https://pattae-melissa-nondoubtingly.ngrok-free.dev/api/integrations/channex/webhook"

# IDs من الـ Mapping الموجود
PROPERTY_ID = "a10bc75f-629f-4cd6-97a4-d735a38912ee"
ROOM_TYPE_ID = "57b03e60-5b32-43ed-a178-ff001906d7ec"
RATE_PLAN_ID = "1247dd48-d671-4e6b-987d-058e1167d3cb"

# ==========================================
# إنشاء بيانات الحجز التجريبي
# ==========================================
booking_id = str(uuid.uuid4())

payload = {
    "event": "booking.new",  # Combined format for proper routing
    "property_id": PROPERTY_ID,  # Property ID at root level
    "data": {
        "id": booking_id,
        "reservation_id": booking_id,
        "unique_id": f"MNAM-TEST-{booking_id[:8].upper()}",
        "property_id": PROPERTY_ID,
        "room_type_id": ROOM_TYPE_ID,
        "rate_plan_id": RATE_PLAN_ID,
        "status": "new",
        "arrival_date": "2026-02-15",
        "departure_date": "2026-02-18",
        "guest": {
            "name": "محمد التجريبي",
            "phone": "+966555123456",
            "email": "test@example.com"
        },
        "adults": 2,
        "children": 0,
        "infants": 0,
        "currency": "SAR",
        "total_price": "750.00",
        "ota_name": "Airbnb",
        "created_at": datetime.now().isoformat() + "Z"
    }
}

# ==========================================
# إرسال الطلب
# ==========================================
print("=" * 50)
print("🧪 إرسال حجز تجريبي للـ Webhook")
print("=" * 50)
print(f"📍 URL: {WEBHOOK_URL}")
print(f"🆔 Booking ID: {booking_id}")
print(f"📅 التاريخ: 2026-02-15 إلى 2026-02-18")
print(f"👤 الضيف: محمد التجريبي")
print(f"💰 المبلغ: 750 SAR")
print()

try:
    response = requests.post(
        WEBHOOK_URL,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Channex-Webhook/1.0"
        },
        timeout=30
    )
    
    print(f"✅ Status Code: {response.status_code}")
    print(f"📋 Response:")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except:
        print(response.text)
    
    if response.status_code == 200:
        print()
        print("=" * 50)
        print("✅ تم إرسال الحجز بنجاح!")
        print("👀 تحقق من صفحة الحجوزات في MNAM Dashboard")
        print("=" * 50)
    else:
        print()
        print("❌ حدث خطأ في إرسال الحجز")
        
except Exception as e:
    print(f"❌ Error: {e}")
