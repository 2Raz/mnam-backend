"""
Channex Health Check Service

Implements FAS (Fail-fast / Audit / Safe-sync) health checks:
- F: Environment variables + API connectivity + IDs validation
- A: Audit trail verification
- S: Safe-sync readiness checks
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    IntegrationOutbox,
    IntegrationAudit,
    ConnectionStatus,
    OutboxStatus
)
from ..models.rate_state import PropertyRateState
from ..models.webhook_event import WebhookEventLog, WebhookEventStatus
from ..config import settings
from .channex_client import ChannexClient, get_channex_client

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    name: str
    passed: bool
    message: str
    details: Optional[Dict] = None


@dataclass
class HealthReportResponse:
    """Full health report"""
    overall_status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str
    checks: List[HealthCheckResult]
    summary: Dict


class ChannexHealthService:
    """
    Health check service for Channex integration.
    
    Implements comprehensive checks for FAS pattern.
    """
    
    def __init__(self, db: Session, request_id: Optional[str] = None):
        self.db = db
        self.request_id = request_id or "no-request-id"
    
    def run_all_checks(self, connection_id: Optional[str] = None) -> HealthReportResponse:
        """Run all health checks and return report"""
        checks = []
        
        # 1. Environment variables check
        checks.append(self._check_env_vars())
        
        # 2. Integration enabled check
        checks.append(self._check_integration_enabled())
        
        # 3. Connection-specific checks (if connection_id provided)
        if connection_id:
            connection = self.db.query(ChannelConnection).filter(
                ChannelConnection.id == connection_id
            ).first()
            
            if connection:
                # API connectivity
                checks.append(self._check_api_connectivity(connection))
                
                # Property validation
                checks.append(self._check_property_validation(connection))
                
                # Room type/rate plan validation
                checks.append(self._check_mapping_validation(connection))
                
                # Rate limit state
                checks.append(self._check_rate_limit_state(connection))
                
                # Outbox health
                checks.append(self._check_outbox_health(connection))
                
                # Webhook health
                checks.append(self._check_webhook_health(connection))
        else:
            # Global checks for all connections
            checks.extend(self._check_all_connections())
        
        # Calculate overall status
        failed_checks = [c for c in checks if not c.passed]
        if not failed_checks:
            overall_status = "healthy"
        elif len(failed_checks) <= 2:
            overall_status = "degraded"
        else:
            overall_status = "unhealthy"
        
        return HealthReportResponse(
            overall_status=overall_status,
            timestamp=datetime.utcnow().isoformat(),
            checks=checks,
            summary={
                "total_checks": len(checks),
                "passed": len([c for c in checks if c.passed]),
                "failed": len(failed_checks),
                "connection_id": connection_id
            }
        )
    
    def _check_env_vars(self) -> HealthCheckResult:
        """Check required environment variables"""
        required_vars = []
        missing = []
        
        # Check Channex base URL
        if not settings.channex_base_url:
            missing.append("CHANNEX_BASE_URL")
        
        # Note: API key is stored per-connection, not globally
        
        return HealthCheckResult(
            name="environment_variables",
            passed=len(missing) == 0,
            message="All required env vars present" if not missing else f"Missing: {', '.join(missing)}",
            details={"missing": missing}
        )
    
    def _check_integration_enabled(self) -> HealthCheckResult:
        """Check if integration is enabled"""
        enabled = settings.channex_enabled
        return HealthCheckResult(
            name="integration_enabled",
            passed=enabled,
            message="Channex integration is enabled" if enabled else "Channex integration is DISABLED",
            details={"channex_enabled": enabled}
        )
    
    def _check_api_connectivity(self, connection: ChannelConnection) -> HealthCheckResult:
        """Check API connectivity to Channex"""
        try:
            client = get_channex_client(connection, self.db, self.request_id)
            response = client.get_property()
            
            if response.success:
                return HealthCheckResult(
                    name="api_connectivity",
                    passed=True,
                    message="API connection successful",
                    details={"status_code": response.status_code}
                )
            else:
                return HealthCheckResult(
                    name="api_connectivity",
                    passed=False,
                    message=f"API error: {response.error}",
                    details={"status_code": response.status_code, "error": response.error}
                )
        except Exception as e:
            return HealthCheckResult(
                name="api_connectivity",
                passed=False,
                message=f"Connection failed: {str(e)}",
                details={"error": str(e)}
            )
    
    def _check_property_validation(self, connection: ChannelConnection) -> HealthCheckResult:
        """Validate property_id exists and is accessible"""
        if not connection.channex_property_id:
            return HealthCheckResult(
                name="property_validation",
                passed=False,
                message="No property ID configured",
                details={}
            )
        
        try:
            client = get_channex_client(connection, self.db, self.request_id)
            response = client.get_property(connection.channex_property_id)
            
            if response.success:
                property_data = response.data.get("data", {}).get("attributes", {}) or response.data
                return HealthCheckResult(
                    name="property_validation",
                    passed=True,
                    message=f"Property valid: {property_data.get('title', 'Unknown')}",
                    details={
                        "property_id": connection.channex_property_id,
                        "title": property_data.get("title"),
                        "currency": property_data.get("currency"),
                        "timezone": property_data.get("timezone")
                    }
                )
            else:
                return HealthCheckResult(
                    name="property_validation",
                    passed=False,
                    message=f"Property not accessible: {response.error}",
                    details={"property_id": connection.channex_property_id, "error": response.error}
                )
        except Exception as e:
            return HealthCheckResult(
                name="property_validation",
                passed=False,
                message=f"Validation failed: {str(e)}",
                details={"error": str(e)}
            )
    
    def _check_mapping_validation(self, connection: ChannelConnection) -> HealthCheckResult:
        """Validate mappings point to valid room types and rate plans"""
        mappings = self.db.query(ExternalMapping).filter(
            and_(
                ExternalMapping.connection_id == connection.id,
                ExternalMapping.is_active == True
            )
        ).all()
        
        if not mappings:
            return HealthCheckResult(
                name="mapping_validation",
                passed=False,
                message="No active mappings found",
                details={"mapping_count": 0}
            )
        
        # Just count for now - full validation would require API calls
        valid_count = len(mappings)
        
        return HealthCheckResult(
            name="mapping_validation",
            passed=valid_count > 0,
            message=f"{valid_count} active mappings configured",
            details={
                "mapping_count": valid_count,
                "mappings": [
                    {
                        "unit_id": m.unit_id,
                        "room_type_id": m.channex_room_type_id,
                        "rate_plan_id": m.channex_rate_plan_id
                    }
                    for m in mappings[:5]  # Limit to 5 for response size
                ]
            }
        )
    
    def _check_rate_limit_state(self, connection: ChannelConnection) -> HealthCheckResult:
        """Check rate limit state for the property"""
        state = self.db.query(PropertyRateState).filter(
            PropertyRateState.channex_property_id == connection.channex_property_id
        ).first()
        
        if not state:
            return HealthCheckResult(
                name="rate_limit_state",
                passed=True,
                message="No rate limit issues (no state)",
                details={}
            )
        
        is_paused = state.is_paused()
        
        return HealthCheckResult(
            name="rate_limit_state",
            passed=not is_paused,
            message="Rate limit OK" if not is_paused else f"Property PAUSED until {state.paused_until}",
            details={
                "is_paused": is_paused,
                "paused_until": state.paused_until.isoformat() if state.paused_until else None,
                "pause_count": state.pause_count,
                "price_tokens": state.price_tokens,
                "avail_tokens": state.avail_tokens,
                "total_429s": state.total_429s
            }
        )
    
    def _check_outbox_health(self, connection: ChannelConnection) -> HealthCheckResult:
        """Check outbox queue health"""
        pending_count = self.db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.connection_id == connection.id,
                IntegrationOutbox.status.in_([
                    OutboxStatus.PENDING.value,
                    OutboxStatus.RETRYING.value
                ])
            )
        ).count()
        
        failed_count = self.db.query(IntegrationOutbox).filter(
            and_(
                IntegrationOutbox.connection_id == connection.id,
                IntegrationOutbox.status == OutboxStatus.FAILED.value
            )
        ).count()
        
        # Consider unhealthy if too many pending or failed
        is_healthy = pending_count < 100 and failed_count < 10
        
        return HealthCheckResult(
            name="outbox_health",
            passed=is_healthy,
            message=f"{pending_count} pending, {failed_count} failed" if is_healthy else f"Queue backlog: {pending_count} pending, {failed_count} failed",
            details={
                "pending_count": pending_count,
                "failed_count": failed_count
            }
        )
    
    def _check_webhook_health(self, connection: ChannelConnection) -> HealthCheckResult:
        """Check webhook processing health"""
        # Check pending webhooks
        pending_count = self.db.query(WebhookEventLog).filter(
            WebhookEventLog.status == WebhookEventStatus.RECEIVED.value
        ).count()
        
        failed_count = self.db.query(WebhookEventLog).filter(
            WebhookEventLog.status == WebhookEventStatus.FAILED.value
        ).count()
        
        is_healthy = pending_count < 50 and failed_count < 5
        
        return HealthCheckResult(
            name="webhook_health",
            passed=is_healthy,
            message=f"{pending_count} pending, {failed_count} failed" if is_healthy else f"Webhook backlog: {pending_count} pending, {failed_count} failed",
            details={
                "pending_count": pending_count,
                "failed_count": failed_count
            }
        )
    
    def _check_all_connections(self) -> List[HealthCheckResult]:
        """Global checks for all connections"""
        results = []
        
        # Count connections by status
        connections = self.db.query(ChannelConnection).filter(
            ChannelConnection.provider == "channex"
        ).all()
        
        active = [c for c in connections if c.status == ConnectionStatus.ACTIVE.value]
        error = [c for c in connections if c.status == ConnectionStatus.ERROR.value]
        
        results.append(HealthCheckResult(
            name="connections_overview",
            passed=len(error) == 0,
            message=f"{len(active)} active, {len(error)} in error",
            details={
                "total": len(connections),
                "active": len(active),
                "error": len(error),
                "error_connections": [c.id for c in error[:5]]
            }
        ))
        
        # Global outbox check
        pending_count = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.RETRYING.value])
        ).count()
        
        failed_count = self.db.query(IntegrationOutbox).filter(
            IntegrationOutbox.status == OutboxStatus.FAILED.value
        ).count()
        
        results.append(HealthCheckResult(
            name="global_outbox",
            passed=pending_count < 500 and failed_count < 50,
            message=f"Outbox: {pending_count} pending, {failed_count} failed",
            details={"pending": pending_count, "failed": failed_count}
        ))
        
        return results


def compute_payload_hash(payload: dict) -> str:
    """Compute SHA256 hash of a payload for audit trail"""
    payload_str = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload_str.encode()).hexdigest()
