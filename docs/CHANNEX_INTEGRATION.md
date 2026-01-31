# Channex Integration Guide

## Overview

MNAM integrates with Channex as a **Channel Manager** to distribute units to OTAs (Airbnb, Booking.com, etc.) and receive bookings.

**MNAM is the Source of Truth (SoT)** for:
- Unit data
- Pricing (via dynamic pricing engine)
- Availability (calculated from bookings)
- Restrictions/rules

Channex handles:
- Distribution to OTA channels
- Receiving bookings from channels
- Webhook notifications to MNAM

## Architecture

```
┌─────────────┐    ARI Push     ┌─────────────┐    Distribute    ┌─────────────┐
│    MNAM     │ ───────────────►│   Channex   │ ───────────────► │   OTAs      │
│  (Backend)  │                 │ (Channel    │                  │ (Airbnb,    │
│             │ ◄───────────────│  Manager)   │ ◄─────────────── │  Booking,   │
│             │    Webhooks     │             │    Bookings      │  etc.)      │
└─────────────┘                 └─────────────┘                  └─────────────┘
```

## FAS Pattern (Fail-fast / Audit / Safe-sync)

This integration implements the FAS pattern for production readiness:

### F - Fail-fast Checks
- Verify environment variables before startup
- Validate API connectivity on connect
- Check property_id/room_type_id/rate_plan_id relationships
- Validate payload size before sending

### A - Audit Trail
- **IntegrationLog**: All API calls logged with request/response
- **IntegrationAudit**: Every sync operation tracked with payload hash
- **WebhookEventLog**: Raw webhook storage for replay

### S - Safe-sync
- **Token bucket rate limiting** per property
- **Outbox pattern** for reliable delivery
- **Dedup/merge** for overlapping events
- **Exponential backoff** on failures
- **Idempotency keys** to prevent duplicates

## Entity Mapping

| MNAM Entity | Channex Entity | Notes |
|-------------|----------------|-------|
| Project | Property | 1:1 mapping, connection is per project |
| Unit | Room Type | 1:1 for vacation rentals (inventory=1) |
| PricingPolicy | Rate Plan | 1 rate plan per unit initially |
| Booking | Reservation | Created via webhooks |

## Database Models

### ChannelConnection
Stores connection credentials per project.
```python
- project_id           # MNAM internal project ID
- channex_property_id  # External Channex property ID
- api_key              # NEVER exposed to frontend
- status               # active/inactive/error/pending
- last_sync_at         # Last successful sync
```

### ExternalMapping
Maps MNAM units to Channex room types.
```python
- unit_id              # MNAM unit ID
- channex_room_type_id # Channex room type
- channex_rate_plan_id # Channex rate plan
- last_price_sync_at   # Last price push
- last_avail_sync_at   # Last availability push
```

### IntegrationOutbox
Queue for outbound events (transactional outbox pattern).
```python
- event_type           # PRICE_UPDATE, AVAIL_UPDATE, FULL_SYNC
- payload              # Data to send
- status               # pending/processing/completed/failed/retrying
- attempts/max_attempts
- idempotency_key      # For dedup
```

### WebhookEventLog
Raw webhook storage for async processing.
```python
- event_id             # From Channex webhook
- payload_json         # Raw payload
- status               # received/processing/processed/failed/skipped
```

### PropertyRateState
Token bucket rate limiting per Channex property.
```python
- channex_property_id
- price_tokens         # 10/min for prices
- avail_tokens         # 10/min for availability  
- paused_until         # On 429, pause property
- pause_count          # For exponential backoff
```

### IntegrationAudit (NEW)
Audit trail for all sync operations.
```python
- direction            # outbound/inbound
- entity_type          # availability/rate/restrictions/booking
- payload_hash         # SHA256 for verification
- status               # pending/success/failed
- retry_count
- duration_ms
```

## Environment Variables

```env
# Required
CHANNEX_BASE_URL=https://app.channex.io/api/v1

# Enable/Disable (NEW)
CHANNEX_ENABLED=true                      # Set to false to disable integration

# Security (NEW)
CHANNEX_WEBHOOK_SECRET=your-webhook-secret  # HMAC-SHA256 signature validation
CHANNEX_ALLOWED_IPS=                        # Comma-separated IP allowlist
CHANNEX_WEBHOOK_REPLAY_WINDOW=300           # Reject events older than 5 min

# Configuration
WEEKEND_DAYS=4,5                          # Friday, Saturday (Saudi)
CHANNEX_PRICE_RATE_LIMIT=10               # Requests per minute
CHANNEX_AVAIL_RATE_LIMIT=10
CHANNEX_SYNC_DAYS=365                     # Days ahead to push
CHANNEX_MAX_PAYLOAD_BYTES=10000000        # 10MB max
```

## API Endpoints

### Health & Status (NEW)

```bash
# Comprehensive health check (FAS checks)
GET /api/integrations/channex/health?connection_id=xxx

# Quick status overview
GET /api/integrations/channex/status
```

### Connect Flow

```bash
# 1. List available Channex properties
GET /api/integrations/channex/properties?api_key=xxx

# 2. Connect project to Channex property
POST /api/integrations/channex/connect
{
  "project_id": "uuid",
  "api_key": "xxx",
  "channex_property_id": "xxx"
}

# 3. Sync room types and rate plans
POST /api/integrations/channex/sync?connection_id=xxx&auto_map=true
```

### Sync Operations (NEW)

```bash
# Full sync (prices + availability for all units)
POST /api/integrations/channex/sync/full?connection_id=xxx&days_ahead=365

# Incremental sync (specific unit or type)
POST /api/integrations/channex/sync/incremental?connection_id=xxx&sync_type=prices&days_ahead=30

# Legacy sync endpoint
POST /api/integrations/connections/{connection_id}/sync
{
  "sync_type": "full",  # or "prices", "availability"
  "days_ahead": 365
}
```

### Webhooks

```bash
# Channex sends webhooks to:
POST /api/integrations/channex/webhook
# Headers: X-Channex-Signature (optional HMAC)

# Check pending webhooks
GET /api/integrations/channex/webhook/pending

# Process pending webhooks manually
POST /api/integrations/channex/webhook/process?limit=50
```

### Admin/Monitoring

```bash
# View connection health
GET /api/integrations/connections/{id}/health

# View failed outbox events
GET /api/integrations/outbox/failures

# Retry a failed event
POST /api/integrations/outbox/{event_id}/retry

# View integration logs
GET /api/integrations/logs?connection_id=xxx
```

## Running the Worker

The outbox worker processes pending events. Run it as a separate process:

```bash
# Start worker with default settings
python worker.py

# With custom interval (seconds)
WORKER_INTERVAL=10 python worker.py

# With custom batch size
WORKER_BATCH_SIZE=100 python worker.py
```

The worker processes:
1. **Outbox events** (push to Channex)
2. **Webhook events** (booking creation)

## Rate Limiting

Channex enforces per-property rate limits:
- **10 price+restrictions requests/min** per property
- **10 availability requests/min** per property

MNAM handles this with:
1. **Token bucket** per property (separate buckets for price/avail)
2. **On 429**: Pause property for 60s, then exponential backoff (60s, 120s, 240s, max 600s)
3. **Dedup/merge**: Overlapping events are merged (last-write-wins)

## Webhook Security (NEW)

### Signature Validation
If `CHANNEX_WEBHOOK_SECRET` is configured, webhooks are validated with HMAC-SHA256:
```
expected = hmac.sha256(webhook_secret, request_body)
compare(expected, X-Channex-Signature header)
```

### IP Allowlist
If `CHANNEX_ALLOWED_IPS` is configured, only requests from those IPs are accepted.

### Replay Protection
Events older than `CHANNEX_WEBHOOK_REPLAY_WINDOW` seconds are rejected.

## Troubleshooting

### Integration Disabled
Symptoms:
- All endpoints return "Channex integration is disabled"

Solutions:
1. Set `CHANNEX_ENABLED=true` in environment

### 429 Rate Limited

Symptoms:
- Events stuck in `retrying` status
- PropertyRateState shows `paused_until` in future

Solutions:
1. Wait for pause to expire (auto-recovery)
2. Reduce batch sizes
3. Check for duplicate sync triggers

```sql
-- Check rate state
SELECT * FROM property_rate_states 
WHERE paused_until > NOW();

-- Check pending events
SELECT connection_id, COUNT(*) 
FROM integration_outbox 
WHERE status IN ('pending', 'retrying')
GROUP BY connection_id;
```

### 401 Unauthorized

Symptoms:
- Connection status is `error`
- Logs show "Invalid API key"

Solutions:
1. Verify API key in Channex dashboard
2. Check API key hasn't expired
3. Regenerate API key if needed

### Mappings Not Found

Symptoms:
- Webhooks fail with "No mapping for room type"
- Prices not syncing

Solutions:
1. Run sync to refresh mappings
2. Create mappings manually
3. Verify unit exists in project

```sql
-- Check mappings
SELECT em.*, cc.channex_property_id
FROM external_mappings em
JOIN channel_connections cc ON em.connection_id = cc.id
WHERE em.unit_id = 'xxx';
```

### Webhook Duplicates

Symptoms:
- Same booking created multiple times

This shouldn't happen due to idempotency, but if it does:
1. Check `inbound_idempotency` table
2. Check `webhook_event_logs` for duplicate event_ids
3. Verify unique constraint is working

## Security

- **API keys are NEVER exposed** to frontend
- Stored in DB, referenced only by connection_id
- Webhook signatures validated when secret is configured
- All logs mask sensitive fields (phone, email, api_key)
- IP allowlist for webhooks (optional)
- Replay protection for webhooks

## Testing

Run tests:
```bash
cd mnam-backend
pytest tests/test_channex_integration.py -v
```

Key test scenarios:
- Token bucket rate limiting
- Webhook idempotency
- Webhook security (signature, IP, replay)
- Outbox dedup/merge
- Booking status mapping
- Client authentication header
- Integration audit

## Staging Setup Checklist

1. Set environment variables in Railway:
   ```
   CHANNEX_ENABLED=true
   CHANNEX_BASE_URL=https://staging.channex.io/api/v1
   CHANNEX_WEBHOOK_SECRET=your-staging-secret
   CHANNEX_SYNC_DAYS=30
   ```

2. Run database migrations:
   ```bash
   alembic upgrade head
   ```

3. Start the worker:
   ```bash
   python worker.py
   ```

4. Test health endpoint:
   ```bash
   curl https://your-api/api/integrations/channex/health
   ```

5. Connect a test property:
   ```bash
   curl -X POST https://your-api/api/integrations/channex/connect \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"project_id": "xxx", "api_key": "CHANNEX_KEY", "channex_property_id": "xxx"}'
   ```

6. Trigger full sync:
   ```bash
   curl -X POST "https://your-api/api/integrations/channex/sync/full?connection_id=xxx"
   ```

## Production Checklist

- [ ] `CHANNEX_ENABLED=true`
- [ ] `CHANNEX_BASE_URL=https://app.channex.io/api/v1`
- [ ] `CHANNEX_WEBHOOK_SECRET` set to secure value
- [ ] `CHANNEX_ALLOWED_IPS` configured (if Channex provides static IPs)
- [ ] Worker process running with monitoring
- [ ] Sentry/alerts configured for errors
- [ ] Health endpoint monitored
- [ ] Rate limits appropriate for property count


## 🔐 API Key Security & Rotation

### If Your API Key is Compromised:
1. Go to Channex Dashboard → Settings → API Keys
2. Click "Revoke" on the compromised key
3. Click "Create New API Key"
4. Update your .env file with the new key
5. Restart your application

### Security Rules:
- NEVER commit API key to git
- NEVER log API key
- NEVER return API key in API responses
- Store ONLY in .env (local) or environment variables (production)


## 🧪 Local Testing Endpoints

These endpoints are for **local development only** - they use env vars directly without DB connections.

### Required Environment Variables

```env
CHANNEX_BASE_URL=https://staging.channex.io/api/v1
CHANNEX_API_KEY=your-api-key
CHANNEX_PROPERTY_ID=a10bc75f-629f-4cd6-97a4-d735a38912ee
CHANNEX_ROOM_TYPE_ID=f1edd109-7835-4296-956e-b7b778d43728
CHANNEX_RATE_PLAN_ID=30164cf5-2f0a-4a8d-a6fb-8116d2559e6d
```

### Endpoints

#### 1. Health Check
```bash
curl http://localhost:8000/integrations/channex/local/health
```

#### 2. Validate IDs
```bash
curl http://localhost:8000/integrations/channex/local/validate-ids
```

#### 3. Test Availability Update
```bash
# Default: today + 7 days, availability = 1
curl -X POST http://localhost:8000/integrations/channex/local/test/availability

# Custom dates and availability
curl -X POST http://localhost:8000/integrations/channex/local/test/availability \
  -H "Content-Type: application/json" \
  -d '{"date_from": "2026-01-20", "date_to": "2026-01-25", "availability": 2}'
```

#### 4. Test Rate Update
```bash
# Default: today + 7 days, rate = 100 SAR
curl -X POST http://localhost:8000/integrations/channex/local/test/rate

# Custom dates and rate (rate is sent as cents: 150.00 → 15000)
curl -X POST http://localhost:8000/integrations/channex/local/test/rate \
  -H "Content-Type: application/json" \
  -d '{"date_from": "2026-01-20", "date_to": "2026-01-25", "rate": 150.00}'
```

### Quick Start (Windows CMD)

```cmd
cd mnam-backend
set CHANNEX_BASE_URL=https://staging.channex.io/api/v1
set CHANNEX_API_KEY=your-api-key
set CHANNEX_PROPERTY_ID=a10bc75f-629f-4cd6-97a4-d735a38912ee
set CHANNEX_ROOM_TYPE_ID=f1edd109-7835-4296-956e-b7b778d43728
set CHANNEX_RATE_PLAN_ID=30164cf5-2f0a-4a8d-a6fb-8116d2559e6d
uvicorn app.main:app --reload
```

---

## 📚 Channex API Reference

### Availability & Rates Endpoints

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get Restrictions/Rates | `/restrictions?filter[property_id]=...` | GET |
| Get Availability | `/availability?filter[property_id]=...` | GET |
| **Update Rates** | `/restrictions` | POST |
| **Update Availability** | `/availability` | POST |

### Update Rates Payload

```json
POST /restrictions
{
  "values": [{
    "property_id": "uuid",
    "rate_plan_id": "uuid",
    "date": "2026-01-20",
    "rate": 15000  // Integer cents (150.00 SAR = 15000)
  }]
}

// Or with date range:
{
  "values": [{
    "property_id": "uuid",
    "rate_plan_id": "uuid",
    "date_from": "2026-01-20",
    "date_to": "2026-01-25",
    "rate": 15000
  }]
}
```

### Rate Fields (Optional)

- `rate` - Integer (cents) or String ("150.00")
- `min_stay_arrival` - Positive integer
- `min_stay_through` - Positive integer
- `max_stay` - Non-negative integer
- `closed_to_arrival` - Boolean
- `closed_to_departure` - Boolean
- `stop_sell` - Boolean

### Update Availability Payload

```json
POST /availability
{
  "values": [{
    "property_id": "uuid",
    "room_type_id": "uuid",
    "date": "2026-01-20",
    "availability": 2
  }]
}

// Or with date range:
{
  "values": [{
    "property_id": "uuid",
    "room_type_id": "uuid",
    "date_from": "2026-01-20",
    "date_to": "2026-01-25",
    "availability": 2
  }]
}
```

### Rate Limits

- **10 restrictions/rates requests per minute** per property
- **10 availability requests per minute** per property
- On 429: Wait 60 seconds, then retry with exponential backoff

### Authentication

All requests require the `user-api-key` header:
```
user-api-key: your-api-key
```