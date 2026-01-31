"""
Enhanced Channex API Client

A production-ready wrapper for the Channex API that handles:
- Authentication via user-api-key header (NOT Bearer token)
- Token bucket rate limiting per property (prices + availability separately)
- Request/response logging with request_id
- Error handling with structured mapping
- Exponential backoff with 429 pause handling

Channex API Documentation: https://docs.channex.io/
"""

import time
import json
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    import requests

from sqlalchemy.orm import Session

from ..config import settings
from ..models.channel_integration import (
    ChannelConnection,
    IntegrationLog,
    ConnectionStatus
)
from ..models.rate_state import PropertyRateState
from ..database import SessionLocal

logger = logging.getLogger(__name__)


@dataclass
class ChannexResponse:
    """Wrapper for Channex API responses with structured error info"""
    success: bool
    status_code: int
    data: Optional[Dict] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    raw_response: Optional[str] = None
    request_id: Optional[str] = None
    should_retry: bool = False
    rate_limited: bool = False


@dataclass
class ChannexError:
    """Structured error from Channex API"""
    code: str
    message: str
    status_code: int
    retryable: bool = False


# Error mapping for Channex responses
ERROR_MAP = {
    401: ChannexError("unauthorized", "Invalid or missing API key", 401, False),
    403: ChannexError("forbidden", "Access denied to this resource", 403, False),
    404: ChannexError("not_found", "Resource not found", 404, False),
    422: ChannexError("validation_error", "Invalid request data", 422, False),
    429: ChannexError("rate_limited", "Too many requests", 429, True),
    500: ChannexError("server_error", "Channex server error", 500, True),
    502: ChannexError("bad_gateway", "Channex gateway error", 502, True),
    503: ChannexError("service_unavailable", "Channex service unavailable", 503, True),
}


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter with DB persistence.
    
    Maintains separate buckets for price and availability requests.
    Uses PropertyRateState model for persistence across restarts.
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_state(self, channex_property_id: str) -> PropertyRateState:
        """Get or create rate state for a property"""
        state = self.db.query(PropertyRateState).filter(
            PropertyRateState.channex_property_id == channex_property_id
        ).first()
        
        if not state:
            state = PropertyRateState(channex_property_id=channex_property_id)
            self.db.add(state)
            self.db.flush()
        
        return state
    
    def can_make_request(
        self,
        channex_property_id: str,
        bucket: str = "price"
    ) -> Tuple[bool, float]:
        """
        Check if we can make a request for this property.
        
        Returns: (can_request, wait_time_seconds)
        """
        state = self.get_or_create_state(channex_property_id)
        
        # Check if paused
        if state.is_paused():
            wait_time = (state.paused_until - datetime.utcnow()).total_seconds()
            return False, max(0, wait_time)
        
        # Check token availability
        state.refill_tokens(bucket)
        
        if bucket == "price":
            if state.price_tokens >= 1.0:
                return True, 0
            else:
                return False, state.wait_time_for_token(bucket)
        else:
            if state.avail_tokens >= 1.0:
                return True, 0
            else:
                return False, state.wait_time_for_token(bucket)
    
    def consume(self, channex_property_id: str, bucket: str = "price") -> bool:
        """Consume a token. Returns True if successful."""
        state = self.get_or_create_state(channex_property_id)
        
        if state.is_paused():
            return False
        
        success = state.consume_token(bucket)
        self.db.commit()
        return success
    
    def on_429(self, channex_property_id: str):
        """Handle 429 response - pause the property"""
        state = self.get_or_create_state(channex_property_id)
        state.pause_on_429()
        self.db.commit()
        logger.warning(
            f"Property {channex_property_id} paused until "
            f"{state.paused_until} due to 429 (attempt {state.pause_count})"
        )
    
    def on_success(self, channex_property_id: str):
        """Handle successful request - potentially clear pause"""
        state = self.get_or_create_state(channex_property_id)
        state.clear_pause()
        self.db.commit()


class ChannexClient:
    """
    Production-ready client for Channex API operations.
    
    Features:
    - Proper auth header: user-api-key (NOT Bearer)
    - Token bucket rate limiting per property
    - Separate buckets for prices vs availability
    - Full request/response logging with request_id
    - Structured error mapping
    - Exponential backoff with 429 pause
    """
    
    def __init__(
        self,
        api_key: str,
        channex_property_id: str,
        connection_id: Optional[str] = None,
        db: Optional[Session] = None,
        request_id: Optional[str] = None
    ):
        self.api_key = api_key
        self.channex_property_id = channex_property_id
        self.connection_id = connection_id
        self.db = db
        self.request_id = request_id or "no-request-id"
        
        # Use base URL from config (staging vs production)
        self.base_url = settings.channex_base_url
        
        # Rate limiter (only if DB provided)
        self.rate_limiter = TokenBucketRateLimiter(db) if db else None
        
        # Retry configuration
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 30.0
        self.timeout = 30
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Get headers for API requests.
        
        IMPORTANT: Channex uses "user-api-key" header, NOT Bearer token!
        """
        return {
            "Content-Type": "application/json",
            "user-api-key": self.api_key,
            "User-Agent": "MNAM-Backend/2.0",
            "X-Request-ID": self.request_id
        }
    
    def _log_request(
        self,
        method: str,
        url: str,
        payload: Optional[Dict],
        response_status: int,
        response_body: Any,
        success: bool,
        error: Optional[str],
        duration_ms: int,
        event_type: str = "api_call"
    ):
        """Log API request to IntegrationLog table"""
        if not self.db or not self.connection_id:
            return
        
        try:
            log = IntegrationLog(
                connection_id=self.connection_id,
                log_type="api_call",
                direction="outbound",
                event_type=event_type,
                request_method=method,
                request_url=url[:500],
                request_payload=self._sanitize_payload(payload),
                response_status=response_status,
                response_body=response_body if isinstance(response_body, dict) else {"raw": str(response_body)[:1000]},
                success=success,
                error_message=error[:1000] if error else None,
                duration_ms=duration_ms
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.warning(f"[{self.request_id}] Failed to log request: {e}")
    
    def _sanitize_payload(self, payload: Optional[Dict]) -> Optional[Dict]:
        """Remove sensitive data from payload before logging"""
        if not payload:
            return None
        
        sanitized = payload.copy()
        sensitive_keys = ["api_key", "password", "secret", "token", "authorization", "user-api-key"]
        
        def sanitize_dict(d: Dict) -> Dict:
            result = {}
            for k, v in d.items():
                if any(sk in k.lower() for sk in sensitive_keys):
                    result[k] = "[REDACTED]"
                elif isinstance(v, dict):
                    result[k] = sanitize_dict(v)
                elif isinstance(v, list):
                    result[k] = [sanitize_dict(i) if isinstance(i, dict) else i for i in v]
                else:
                    result[k] = v
            return result
        
        return sanitize_dict(sanitized)
    
    def _map_error(self, status_code: int, response_data: Optional[Dict]) -> ChannexError:
        """Map HTTP status code to structured error"""
        if status_code in ERROR_MAP:
            error = ERROR_MAP[status_code]
            # Try to get more specific message from response
            if response_data:
                msg = response_data.get("error", {}).get("message") or response_data.get("message")
                if msg:
                    return ChannexError(error.code, msg, status_code, error.retryable)
            return error
        
        if status_code >= 500:
            return ChannexError("server_error", f"Server error: {status_code}", status_code, True)
        
        return ChannexError("unknown", f"Unknown error: {status_code}", status_code, False)
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict] = None,
        params: Optional[Dict] = None,
        bucket: str = "price"  # "price" or "avail" for rate limiting
    ) -> ChannexResponse:
        """
        Make an HTTP request to Channex API with rate limiting and retry logic.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        start_time = time.time()
        
        # Check rate limit before making request
        if self.rate_limiter:
            can_request, wait_time = self.rate_limiter.can_make_request(
                self.channex_property_id, bucket
            )
            if not can_request:
                if wait_time > 0:
                    logger.info(f"[{self.request_id}] Rate limited, waiting {wait_time:.2f}s")
                    time.sleep(min(wait_time, 60))  # Cap wait at 60s
                    # Re-check after wait
                    can_request, _ = self.rate_limiter.can_make_request(
                        self.channex_property_id, bucket
                    )
                    if not can_request:
                        return ChannexResponse(
                            success=False,
                            status_code=429,
                            error="Rate limit exceeded, try later",
                            rate_limited=True,
                            request_id=self.request_id
                        )
        
        last_error = None
        last_status = 0
        
        for attempt in range(self.max_retries):
            try:
                # Consume a token
                if self.rate_limiter:
                    self.rate_limiter.consume(self.channex_property_id, bucket)
                
                # Make the request
                if HAS_HTTPX:
                    response = self._httpx_request(method, url, headers, payload, params)
                else:
                    response = self._requests_request(method, url, headers, payload, params)
                
                duration_ms = int((time.time() - start_time) * 1000)
                status_code = response.status_code
                last_status = status_code
                
                # Parse response
                try:
                    data = response.json() if hasattr(response, 'json') else json.loads(response.text)
                except:
                    data = None
                
                # Success
                if 200 <= status_code < 300:
                    if self.rate_limiter:
                        self.rate_limiter.on_success(self.channex_property_id)
                    
                    self._log_request(method, url, payload, status_code, data, True, None, duration_ms)
                    return ChannexResponse(
                        success=True,
                        status_code=status_code,
                        data=data,
                        request_id=self.request_id
                    )
                
                # Rate limited - pause and retry
                if status_code == 429:
                    if self.rate_limiter:
                        self.rate_limiter.on_429(self.channex_property_id)
                    
                    delay = min(self.base_delay * (2 ** attempt) + 60, self.max_delay)
                    logger.warning(f"[{self.request_id}] Rate limited (429), retrying in {delay}s")
                    time.sleep(delay)
                    continue
                
                # Server error - retry
                if status_code >= 500:
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    logger.warning(f"[{self.request_id}] Server error ({status_code}), retrying in {delay}s")
                    time.sleep(delay)
                    continue
                
                # Client error - don't retry
                error = self._map_error(status_code, data)
                self._log_request(method, url, payload, status_code, data, False, error.message, duration_ms)
                return ChannexResponse(
                    success=False,
                    status_code=status_code,
                    error=error.message,
                    error_code=error.code,
                    data=data,
                    should_retry=error.retryable,
                    request_id=self.request_id
                )
                
            except Exception as e:
                last_error = str(e)
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.error(f"[{self.request_id}] Request failed: {e}, retrying in {delay}s")
                time.sleep(delay)
        
        # All retries exhausted
        duration_ms = int((time.time() - start_time) * 1000)
        self._log_request(method, url, payload, last_status, None, False, last_error, duration_ms)
        return ChannexResponse(
            success=False,
            status_code=last_status or 0,
            error=f"All retries failed: {last_error}",
            should_retry=True,
            request_id=self.request_id
        )
    
    def _httpx_request(self, method, url, headers, payload, params):
        """Make request using httpx"""
        with httpx.Client(timeout=self.timeout) as client:
            if method.upper() == "GET":
                return client.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                return client.post(url, headers=headers, json=payload, params=params)
            elif method.upper() == "PUT":
                return client.put(url, headers=headers, json=payload, params=params)
            elif method.upper() == "PATCH":
                return client.patch(url, headers=headers, json=payload, params=params)
            elif method.upper() == "DELETE":
                return client.delete(url, headers=headers, params=params)
    
    def _requests_request(self, method, url, headers, payload, params):
        """Make request using requests"""
        import requests
        if method.upper() == "GET":
            return requests.get(url, headers=headers, params=params, timeout=self.timeout)
        elif method.upper() == "POST":
            return requests.post(url, headers=headers, json=payload, params=params, timeout=self.timeout)
        elif method.upper() == "PUT":
            return requests.put(url, headers=headers, json=payload, params=params, timeout=self.timeout)
        elif method.upper() == "PATCH":
            return requests.patch(url, headers=headers, json=payload, params=params, timeout=self.timeout)
        elif method.upper() == "DELETE":
            return requests.delete(url, headers=headers, params=params, timeout=self.timeout)
    
    # ==================
    # Property Operations
    # ==================
    
    def get_properties(self) -> ChannexResponse:
        """Get all properties accessible with this API key"""
        return self._make_request("GET", "/properties")
    
    def get_property(self, property_id: str = None) -> ChannexResponse:
        """Get property details"""
        pid = property_id or self.channex_property_id
        return self._make_request("GET", f"/properties/{pid}")
    
    def get_room_types(self, property_id: str = None) -> ChannexResponse:
        """Get room types for a property"""
        pid = property_id or self.channex_property_id
        return self._make_request("GET", "/room_types", params={"filter[property_id]": pid})
    
    def get_rate_plans(self, property_id: str = None) -> ChannexResponse:
        """Get rate plans for a property"""
        pid = property_id or self.channex_property_id
        return self._make_request("GET", "/rate_plans", params={"filter[property_id]": pid})
    
    # ==================
    # ARI Operations (Availability, Rates, Inventory)
    # ==================
    
    def update_rates(
        self,
        rate_plan_id: str,
        rates: List[Dict]
    ) -> ChannexResponse:
        """
        Update rates for a rate plan.
        
        Channex expects rates via the /restrictions endpoint in this format:
        {
            "values": [
                {"property_id": "xxx", "rate_plan_id": "xxx", "date": "2024-01-15", "rate": "100.00"},
                {"property_id": "xxx", "rate_plan_id": "xxx", "date": "2024-01-16", "rate": "120.00"}
            ]
        }
        
        NOTE: rate must be a STRING, not a float!
        Uses "price" rate limit bucket.
        """
        # Add property_id and rate_plan_id to each rate entry
        formatted_rates = []
        for rate in rates:
            # Convert rate to string with 2 decimal places (Channex requirement)
            rate_value = rate.get("rate", 0)
            if isinstance(rate_value, (int, float)):
                rate_value = f"{float(rate_value):.2f}"
            
            formatted_rate = {
                "property_id": self.channex_property_id,
                "rate_plan_id": rate_plan_id,
                "date": rate.get("date"),
                "rate": rate_value
            }
            formatted_rates.append(formatted_rate)
        
        # Use /restrictions endpoint (not /rates) - this is the correct endpoint for ARI updates
        endpoint = "/restrictions"
        payload = {"values": formatted_rates}
        return self._make_request("POST", endpoint, payload, bucket="price")
    
    def update_availability(
        self,
        room_type_id: str,
        availability: List[Dict]
    ) -> ChannexResponse:
        """
        Update availability for a room type.
        
        Channex expects availability in this format:
        {
            "values": [
                {"property_id": "xxx", "room_type_id": "xxx", "date": "2024-01-15", "availability": 1},
                {"property_id": "xxx", "room_type_id": "xxx", "date": "2024-01-16", "availability": 0}
            ]
        }
        
        Uses "avail" rate limit bucket.
        """
        # Add property_id and room_type_id to each availability entry
        formatted_avail = []
        for avail in availability:
            formatted_entry = {
                "property_id": self.channex_property_id,
                "room_type_id": room_type_id,
                **avail
            }
            formatted_avail.append(formatted_entry)
        
        endpoint = "/availability"
        payload = {"values": formatted_avail}
        return self._make_request("POST", endpoint, payload, bucket="avail")
    
    def update_restrictions(
        self,
        rate_plan_id: str,
        restrictions: List[Dict]
    ) -> ChannexResponse:
        """
        Update restrictions (min stay, closed to arrival, etc.)
        Uses "price" rate limit bucket (counts toward price+restrictions limit).
        """
        # Add property_id and rate_plan_id to each restriction entry
        formatted_restrictions = []
        for restriction in restrictions:
            formatted_entry = {
                "property_id": self.channex_property_id,
                "rate_plan_id": rate_plan_id,
                **restriction
            }
            formatted_restrictions.append(formatted_entry)
        
        endpoint = "/restrictions"
        payload = {"values": formatted_restrictions}
        return self._make_request("POST", endpoint, payload, bucket="price")
    
    def bulk_update_ari(
        self,
        updates: List[Dict]
    ) -> ChannexResponse:
        """
        Bulk update ARI (Availability, Rates, Inventory).
        More efficient for batched updates.
        """
        endpoint = f"/properties/{self.channex_property_id}/ari"
        payload = {"data": updates}
        return self._make_request("POST", endpoint, payload, bucket="price")
    
    # ==================
    # Booking Operations
    # ==================
    
    def get_bookings(
        self,
        since: Optional[datetime] = None,
        status: Optional[str] = None
    ) -> ChannexResponse:
        """Get bookings from Channex"""
        endpoint = f"/properties/{self.channex_property_id}/bookings"
        params = {}
        if since:
            params["filter[updated_at_gte]"] = since.isoformat()
        if status:
            params["filter[status]"] = status
        return self._make_request("GET", endpoint, params=params)
    
    def get_booking(self, booking_id: str) -> ChannexResponse:
        """Get a specific booking by ID"""
        endpoint = f"/bookings/{booking_id}"
        return self._make_request("GET", endpoint)
    
    def confirm_booking(self, booking_id: str) -> ChannexResponse:
        """Confirm a booking"""
        endpoint = f"/bookings/{booking_id}/confirm"
        return self._make_request("POST", endpoint)
    
    def cancel_booking(
        self,
        booking_id: str,
        reason: Optional[str] = None
    ) -> ChannexResponse:
        """Cancel a booking"""
        endpoint = f"/bookings/{booking_id}/cancel"
        payload = {"reason": reason} if reason else None
        return self._make_request("POST", endpoint, payload)
    
    # ==================
    # Webhook Verification
    # ==================
    
    @staticmethod
    def verify_webhook_signature(
        payload: bytes,
        signature: str,
        secret: str
    ) -> bool:
        """
        Verify Channex webhook signature.
        
        Channex uses HMAC-SHA256 for webhook signatures.
        """
        if not secret or not signature:
            return False
        
        expected = hmac.new(
            secret.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_channex_client(
    connection: ChannelConnection,
    db: Session,
    request_id: Optional[str] = None
) -> ChannexClient:
    """Factory function to create a Channex client from a connection"""
    return ChannexClient(
        api_key=connection.api_key,
        channex_property_id=connection.channex_property_id,
        connection_id=connection.id,
        db=db,
        request_id=request_id
    )
