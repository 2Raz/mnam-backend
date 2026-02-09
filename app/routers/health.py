"""
Health Check Endpoints - NFR Implementation

Provides comprehensive health monitoring:
- /health/live - Liveness check (is process running)
- /health/ready - Readiness check (is service ready to accept traffic)
- /health/detailed - Detailed health with component checks (admin only)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import time
import httpx
from typing import Optional

from ..database import get_db
from ..config import settings
from ..utils.dependencies import get_current_user
from ..models.user import User, UserRole

router = APIRouter(prefix="/health", tags=["Health"])


# ================================
# HEALTH CHECK MODELS
# ================================

def get_db_health(db: Session) -> dict:
    """Check database connectivity and latency"""
    try:
        start = time.time()
        db.execute(text("SELECT 1"))
        latency_ms = (time.time() - start) * 1000
        return {
            "status": "up",
            "latency_ms": round(latency_ms, 2),
            "type": "postgresql" if "postgresql" in str(db.bind.url) else "sqlite"
        }
    except Exception as e:
        return {
            "status": "down",
            "error": str(e)[:100]
        }


async def get_channex_health() -> dict:
    """Check Channex API connectivity"""
    if not settings.channex_enabled:
        return {"status": "disabled"}
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            start = time.time()
            # Simple ping to Channex API (public endpoint)
            response = await client.get(f"{settings.channex_base_url}/health")
            latency_ms = (time.time() - start) * 1000
            
            if response.status_code < 500:
                return {
                    "status": "up",
                    "latency_ms": round(latency_ms, 2)
                }
            return {
                "status": "degraded",
                "http_status": response.status_code
            }
    except httpx.TimeoutException:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "down", "error": str(e)[:50]}


async def get_redis_health() -> dict:
    """Check Redis connectivity (for rate limiting)"""
    # TODO: Implement when Redis is added
    return {"status": "not_configured"}


# ================================
# ENDPOINTS
# ================================

@router.get("/live")
@router.get("/live/")
async def liveness_check():
    """
    Liveness probe - is the process running?
    Used by load balancers and orchestrators.
    """
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/ready")
@router.get("/ready/")
async def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness probe - is the service ready to accept traffic?
    Checks database connectivity.
    """
    db_health = get_db_health(db)
    
    if db_health["status"] == "up":
        return {
            "status": "ready",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # Service not ready - return 503
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "status": "not_ready",
            "reason": "database_unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


@router.get("/detailed")
@router.get("/detailed/")
async def detailed_health_check(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Detailed health check with all component statuses.
    Admin-only endpoint.
    """
    # Only admins and head_admin can see detailed health
    if current_user.role not in [UserRole.ADMIN.value, UserRole.HEAD_ADMIN.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="الوصول مقصور على المديرين"
        )
    
    # Gather all health checks
    db_health = get_db_health(db)
    channex_health = await get_channex_health()
    redis_health = await get_redis_health()
    
    # Determine overall status
    checks = {
        "database": db_health,
        "channex": channex_health,
        "redis": redis_health
    }
    
    # Overall status logic
    critical_down = db_health["status"] == "down"
    any_degraded = any(c.get("status") == "degraded" for c in checks.values())
    
    if critical_down:
        overall_status = "unhealthy"
    elif any_degraded:
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0",
        "environment": settings.environment,
        "checks": checks,
        "config": {
            "channex_enabled": settings.channex_enabled,
            "worker_poll_interval": settings.worker_poll_interval,
            "rate_limit_enabled": True
        }
    }


# ================================
# SIMPLE HEALTH (BACKWARD COMPAT)
# ================================

@router.get("")
@router.get("/")
async def simple_health_check():
    """
    Simple health check - backward compatible.
    Returns basic status without authentication.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "2.0.0"
    }
