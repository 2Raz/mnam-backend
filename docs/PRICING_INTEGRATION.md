# MNAM Pricing Engine & Channex Integration

## Architecture Overview

This document describes the pricing engine and Channex integration implementation for the MNAM property management system.

### Core Principles

1. **MNAM is the Single Source of Truth** - All pricing and availability data originates from MNAM
2. **Outbox Pattern** - All outbound API calls go through a queue with retries and idempotency
3. **Inbound Idempotency** - Webhook events are tracked to prevent duplicate processing
4. **Real-time Discounts** - Intraday discounts are calculated at query time, not stored

---

## Pricing Policy

### Formula

```
base = base_weekday_price
day_price = base if weekday else base * (1 + weekend_markup_percent/100)
active_discount = discount bucket based on local time
final_price = round(day_price * (1 - active_discount/100), 2)
```

### Discount Buckets (Local Time)

| Time Range | Discount Applied |
|------------|------------------|
| 00:00 - 15:59 | 0% (no discount) |
| 16:00 - 20:59 | `discount_16_percent` |
| 21:00 - 22:59 | `discount_21_percent` |
| 23:00 - 23:59 | `discount_23_percent` |

### Weekend Configuration

- **KSA Default**: Friday (4) and Saturday (5)
- **Western**: Saturday (5) and Sunday (6)
- Configurable per unit via `weekend_days` field (comma-separated)

### Example Calculation

```
Base Price: 100 SAR
Weekend Markup: 150%
Discount at 16:00: 10%

Weekday at 10:00:
  day_price = 100
  final_price = 100 (no discount)

Friday at 16:00:
  day_price = 100 * (1 + 1.50) = 250
  final_price = 250 * (1 - 0.10) = 225
```

---

## Data Models

### PricingPolicy

Stores pricing configuration per unit:

| Field | Type | Description |
|-------|------|-------------|
| unit_id | FK | Reference to unit (1:1) |
| base_weekday_price | Decimal | Base price for weekdays |
| weekend_markup_percent | Decimal | % markup for weekends |
| discount_16_percent | Decimal | Discount from 16:00 |
| discount_21_percent | Decimal | Discount from 21:00 |
| discount_23_percent | Decimal | Discount from 23:00 |
| timezone | String | For local time calculations |
| weekend_days | String | Comma-separated day numbers |

### ChannelConnection

Stores Channex API credentials per project:

| Field | Type | Description |
|-------|------|-------------|
| project_id | FK | Reference to project |
| provider | String | "channex" |
| api_key | Text | Channex API key |
| channex_property_id | String | Channex property ID |
| status | Enum | active/inactive/error/pending |
| last_sync_at | DateTime | Last successful sync |

### ExternalMapping

Maps MNAM units to Channex room types:

| Field | Type | Description |
|-------|------|-------------|
| connection_id | FK | Reference to connection |
| unit_id | FK | Reference to unit |
| channex_room_type_id | String | Channex room type ID |
| channex_rate_plan_id | String | Channex rate plan ID |

### IntegrationOutbox

Queue for outbound events:

| Field | Type | Description |
|-------|------|-------------|
| event_type | Enum | PRICE_UPDATE / AVAIL_UPDATE |
| payload | JSON | Event data |
| status | Enum | pending/processing/completed/failed |
| attempts | Int | Retry count |
| idempotency_key | String | For deduplication |

### InboundIdempotency

Tracks processed webhooks:

| Field | Type | Description |
|-------|------|-------------|
| external_event_id | String | Channex event ID |
| external_reservation_id | String | Booking ID |
| result_action | String | created/updated/cancelled |

---

## API Endpoints

### Pricing Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/pricing/policies` | Create pricing policy |
| GET | `/pricing/policies/{unit_id}` | Get pricing policy |
| PUT | `/pricing/policies/{unit_id}` | Update pricing policy |
| DELETE | `/pricing/policies/{unit_id}` | Delete pricing policy |
| GET | `/pricing/calendar/{unit_id}` | Get price calendar |
| GET | `/pricing/realtime/{unit_id}` | Get real-time price |
| POST | `/pricing/calculate-booking` | Calculate booking total |

### Integration Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/integrations/connections` | Create connection |
| GET | `/integrations/connections` | List connections |
| POST | `/integrations/connections/{id}/test` | Test connection |
| GET | `/integrations/connections/{id}/health` | Get health status |
| POST | `/integrations/mappings` | Create unit mapping |
| POST | `/integrations/channex/webhook` | Receive webhooks |
| POST | `/integrations/connections/{id}/sync` | Trigger sync |
| GET | `/integrations/outbox` | List pending events |
| POST | `/integrations/outbox/{id}/retry` | Retry failed event |
| GET | `/integrations/logs` | View integration logs |

---

## Integration Flow

### Outbound: MNAM → Channex

```
1. Pricing policy updated in MNAM
2. System enqueues PRICE_UPDATE event in outbox
3. Background worker picks up event
4. Worker generates price calendar using PricingEngine
5. Worker calls Channex API to update rates
6. On success: mark event completed
7. On failure: schedule retry with exponential backoff
```

### Inbound: Channex → MNAM

```
1. Channex sends webhook to /integrations/channex/webhook
2. Handler parses payload, extracts event type
3. Check idempotency table for duplicate
4. If new: create/update/cancel booking in MNAM
5. Record in idempotency table
6. Enqueue AVAIL_UPDATE to sync availability back to Channex
7. Return success response
```

---

## Background Worker

The outbox worker should run periodically (e.g., every 30 seconds):

```python
from app.services.outbox_worker import OutboxProcessor
from app.database import SessionLocal

def run_worker():
    db = SessionLocal()
    try:
        processor = OutboxProcessor(db)
        success, failures = processor.process_batch(limit=50)
        print(f"Processed: {success} success, {failures} failures")
    finally:
        db.close()
```

### Manual Trigger

The `/integrations/outbox/process` endpoint allows manual triggering for testing.

---

## Configuration

### Environment Variables

Add these to `.env`:

```env
# Channex Integration (optional)
CHANNEX_DEFAULT_TIMEZONE=Asia/Riyadh
```

### Rate Limiting

The Channex API enforces per-property rate limits:
- **10 restrictions/rates requests/min** per property
- **10 availability requests/min** per property
- Automatic throttling with exponential backoff on 429 errors
- Configurable retry attempts (default: 3)

---

## Channex API Reference

### Endpoints

| Operation | Endpoint | Method | Notes |
|-----------|----------|--------|-------|
| Update Rates/Restrictions | `/restrictions` | POST | Requires property_id, rate_plan_id |
| Update Availability | `/availability` | POST | Requires property_id, room_type_id |
| Get Rates | `/restrictions?filter[property_id]=...` | GET | Filter by date range |
| Get Availability | `/availability?filter[property_id]=...` | GET | Filter by date range |

### Update Rates Payload

```json
POST /api/v1/restrictions
{
  "values": [{
    "property_id": "716305c4-561a-4561-a187-7f5b8aeb5920",
    "rate_plan_id": "bab451e7-9ab1-4cc4-aa16-107bf7bbabb2",
    "date": "2026-01-20",
    "rate": 15000  // Integer cents (150.00 = 15000)
  }]
}
```

**Date Range Update:**
```json
{
  "values": [{
    "property_id": "...",
    "rate_plan_id": "...",
    "date_from": "2026-01-20",
    "date_to": "2026-01-31",
    "rate": 15000
  }]
}
```

**With Restrictions:**
```json
{
  "values": [{
    "property_id": "...",
    "rate_plan_id": "...",
    "date_from": "2026-01-20",
    "date_to": "2026-01-31",
    "rate": 15000,
    "min_stay_arrival": 2,
    "closed_to_arrival": false,
    "stop_sell": false
  }]
}
```

### Update Availability Payload

```json
POST /api/v1/availability
{
  "values": [{
    "property_id": "716305c4-561a-4561-a187-7f5b8aeb5920",
    "room_type_id": "bab451e7-9ab1-4cc4-aa16-107bf7bbabb2",
    "date": "2026-01-20",
    "availability": 2
  }]
}
```

### Authentication

All requests require the `user-api-key` header:
```
user-api-key: your-api-key
```

---

## Testing

Run tests with:

```bash
pytest tests/ -v
```

### Test Coverage

- `test_pricing_engine.py`: Pricing formula tests
- `test_channex_webhook.py`: Webhook handling tests
- `test_channex_integration.py`: Integration tests

---

## Database Migration

Apply the migration:

```bash
# Development
alembic upgrade head

# Or use the migrate.bat script
migrate.bat
```

---

## Security Considerations

1. **API Keys**: Stored in database, not exposed in API responses
2. **Webhook Signatures**: HMAC-SHA256 verification supported
3. **Logging**: Sensitive guest data (phone, email) is masked in logs
4. **Rate Limiting**: Built-in protection against API abuse
5. **API Key Rotation**: See CHANNEX_INTEGRATION.md for rotation guide

---

## Future Enhancements

1. **Multiple Rate Plans**: Support different rate plans per unit
2. **Seasonal Pricing**: Date-range based pricing rules
3. **Minimum Stay**: Per-day minimum stay restrictions
4. **Closed Dates**: Block specific dates from booking
5. **Last Room Pricing**: Dynamic pricing based on occupancy
