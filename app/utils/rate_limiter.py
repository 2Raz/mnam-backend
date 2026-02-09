"""
Rate Limiter Configuration - NFR Implementation

Supports both in-memory and Redis storage for rate limiting.
Redis is recommended for production (multiple instances).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from typing import Optional
import os


def get_real_client_ip(request: Request) -> str:
    """Get real client IP behind reverse proxy (Railway/Vercel)"""
    # Check X-Forwarded-For header (set by proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct connection
    return get_remote_address(request)


def get_redis_storage() -> Optional[object]:
    """
    Get Redis storage for rate limiting if configured.
    Returns None if Redis is not available/configured.
    """
    redis_url = os.getenv("REDIS_URL")
    
    if not redis_url:
        return None
    
    try:
        from slowapi.storage import RedisStorage
        import redis
        
        # Parse Redis URL and create connection
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test connection
        redis_client.ping()
        
        print("✅ Redis connected for rate limiting")
        return RedisStorage(redis_client)
        
    except ImportError:
        print("⚠️  Redis package not installed, using in-memory storage")
        return None
    except Exception as e:
        print(f"⚠️  Redis connection failed: {e}, using in-memory storage")
        return None


def create_limiter() -> Limiter:
    """
    Create a rate limiter with appropriate storage backend.
    Uses Redis if available, otherwise falls back to in-memory.
    """
    storage = get_redis_storage()
    
    if storage:
        return Limiter(
            key_func=get_real_client_ip,
            storage=storage,
            default_limits=["100/minute"]
        )
    else:
        # In-memory storage (for development or single instance)
        print("📝 Using in-memory rate limiter storage")
        return Limiter(
            key_func=get_real_client_ip,
            default_limits=["100/minute"]
        )


# Global rate limiter instance
limiter = create_limiter()


# ================================
# RATE LIMIT CONFIGURATIONS
# ================================

# Different rate limits for different operations
RATE_LIMITS = {
    # Authentication - strict limits
    "login": "5/minute",
    "password_reset": "3/hour",
    "token_refresh": "10/minute",
    
    # CRUD Operations - moderate limits
    "booking_create": "30/minute",
    "booking_update": "60/minute",
    "booking_delete": "20/minute",
    
    # Read Operations - relaxed limits
    "booking_list": "100/minute",
    "booking_get": "200/minute",
    
    # Webhooks - higher limits for integrations
    "webhook": "100/minute",
    
    # Export/Reports - lower limits (resource intensive)
    "export": "10/minute",
    "report": "20/minute",
    
    # Search - moderate limits
    "search": "60/minute",
}


def get_rate_limit(operation: str) -> str:
    """Get rate limit for a specific operation."""
    return RATE_LIMITS.get(operation, "100/minute")
