"""
🧪 Test Validation - اختبار التحقق من صحة الحجوزات
هذا السكريبت يختبر كل أنواع الأخطاء المنطقية
"""
import requests
import json
import uuid
from datetime import datetime, timedelta

# ==========================================
# التكوين
# ==========================================
WEBHOOK_URL = "https://pattae-melissa-nondoubtingly.ngrok-free.dev/api/integrations/channex/webhook"
PROPERTY_ID = "a10bc75f-629f-4cd6-97a4-d735a38912ee"
ROOM_TYPE_ID = "57b03e60-5b32-43ed-a178-ff001906d7ec"
RATE_PLAN_ID = "1247dd48-d671-4e6b-987d-058e1167d3cb"

def send_test_booking(test_name, check_in, check_out, price="500.00"):
    """إرسال حجز تجريبي"""
    booking_id = str(uuid.uuid4())
    
    payload = {
        "event": "booking.new",
        "property_id": PROPERTY_ID,
        "data": {
            "id": booking_id,
            "reservation_id": booking_id,
            "property_id": PROPERTY_ID,
            "room_type_id": ROOM_TYPE_ID,
            "rate_plan_id": RATE_PLAN_ID,
            "status": "new",
            "arrival_date": check_in,
            "departure_date": check_out,
            "guest": {
                "name": "اختبار التحقق",
                "phone": "+966555000000",
                "email": "test@test.com"
            },
            "total_price": price,
            "ota_name": "Test",
        }
    }
    
    print(f"\n{'='*60}")
    print(f"🧪 اختبار: {test_name}")
    print(f"   📅 من: {check_in} إلى: {check_out}")
    print(f"   💰 السعر: {price}")
    
    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        result = response.json()
        print(f"   📋 النتيجة: {result.get('action', 'unknown')}")
        if result.get('message'):
            event_id = result.get('message', '').split(': ')[-1] if 'queued' in result.get('action', '') else None
            if event_id:
                print(f"   🆔 Event ID: {event_id[:8]}...")
        return response.status_code, result
    except Exception as e:
        print(f"   ❌ خطأ: {e}")
        return None, None

# ==========================================
# تشغيل الاختبارات
# ==========================================
print("=" * 60)
print("🧪 اختبار التحقق من صحة الحجوزات")
print("=" * 60)

today = datetime.now().date()

# 1. حجز صحيح (تواريخ مستقبلية غير متعارضة)
future_date = (today + timedelta(days=60)).isoformat()
future_date_end = (today + timedelta(days=62)).isoformat()
send_test_booking(
    "✅ حجز صحيح - تواريخ مستقبلية",
    future_date,
    future_date_end,
    "600.00"
)

# 2. تاريخ الخروج قبل الدخول
send_test_booking(
    "❌ تاريخ الخروج قبل الدخول",
    "2026-03-15",
    "2026-03-10",  # قبل تاريخ الدخول!
    "500.00"
)

# 3. نفس تاريخ الدخول والخروج
send_test_booking(
    "❌ نفس تاريخ الدخول والخروج",
    "2026-03-15",
    "2026-03-15",  # نفس اليوم!
    "500.00"
)

# 4. تواريخ في الماضي
past_date = (today - timedelta(days=30)).isoformat()
past_date_end = (today - timedelta(days=28)).isoformat()
send_test_booking(
    "❌ تواريخ في الماضي",
    past_date,
    past_date_end,
    "500.00"
)

# 5. حجز بعيد جداً في المستقبل (أكثر من سنتين)
far_future = (today + timedelta(days=800)).isoformat()
far_future_end = (today + timedelta(days=802)).isoformat()
send_test_booking(
    "❌ تاريخ بعيد جداً (> سنتين)",
    far_future,
    far_future_end,
    "500.00"
)

# 6. إقامة طويلة جداً (أكثر من سنة)
long_stay_start = (today + timedelta(days=30)).isoformat()
long_stay_end = (today + timedelta(days=400)).isoformat()  # 370 يوم
send_test_booking(
    "❌ إقامة طويلة جداً (> 365 ليلة)",
    long_stay_start,
    long_stay_end,
    "50000.00"
)

# 7. سعر سالب
valid_start = (today + timedelta(days=70)).isoformat()
valid_end = (today + timedelta(days=72)).isoformat()
send_test_booking(
    "❌ سعر سالب",
    valid_start,
    valid_end,
    "-500.00"
)

# 8. تعارض مع الحجز الموجود (2026-02-15 إلى 2026-02-18)
send_test_booking(
    "❌ تعارض تواريخ مع حجز موجود",
    "2026-02-16",  # يتداخل مع الحجز الموجود
    "2026-02-19",
    "700.00"
)

print("\n" + "=" * 60)
print("✅ انتهت الاختبارات!")
print("👀 تحقق من النتائج وجدول unmatched_webhook_events")
print("=" * 60)
