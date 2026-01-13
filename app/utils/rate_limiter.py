"""Rate limiter configuration - shared module to avoid circular imports"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request


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


# Global rate limiter instance
limiter = Limiter(key_func=get_real_client_ip)
