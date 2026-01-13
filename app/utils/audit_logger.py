"""Security audit logging module"""
import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import Request


# Configure security logger
security_logger = logging.getLogger("security_audit")
security_logger.setLevel(logging.INFO)

# Console handler with structured format
handler = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s | request_id=%(request_id)s'
)
handler.setFormatter(formatter)
security_logger.addHandler(handler)


class AuditLogContext:
    """Context holder for request-scoped audit data"""
    def __init__(self, request_id: str = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]


def get_request_id(request: Request) -> str:
    """Get or create request ID for correlation"""
    if hasattr(request.state, 'request_id'):
        return request.state.request_id
    return str(uuid.uuid4())[:8]


def log_auth_event(
    event_type: str,
    username: str = None,
    user_id: str = None,
    success: bool = True,
    details: str = None,
    ip_address: str = None,
    request_id: str = None
):
    """Log authentication-related events"""
    extra = {'request_id': request_id or 'N/A'}
    
    status = "SUCCESS" if success else "FAILURE"
    message = f"AUTH:{event_type} | status={status}"
    
    if username:
        message += f" | username={username}"
    if user_id:
        message += f" | user_id={user_id}"
    if ip_address:
        message += f" | ip={ip_address}"
    if details:
        message += f" | details={details}"
    
    if success:
        security_logger.info(message, extra=extra)
    else:
        security_logger.warning(message, extra=extra)


def log_resource_access(
    action: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
    success: bool = True,
    request_id: str = None
):
    """Log resource access for audit trail"""
    extra = {'request_id': request_id or 'N/A'}
    
    message = f"RESOURCE:{action} | type={resource_type} | id={resource_id} | user={user_id}"
    
    if success:
        security_logger.info(message, extra=extra)
    else:
        security_logger.warning(message + " | status=DENIED", extra=extra)


def log_role_change(
    target_user_id: str,
    old_role: str,
    new_role: str,
    changed_by: str,
    request_id: str = None
):
    """Log role/privilege changes"""
    extra = {'request_id': request_id or 'N/A'}
    
    message = f"ROLE_CHANGE | target={target_user_id} | from={old_role} | to={new_role} | by={changed_by}"
    security_logger.info(message, extra=extra)
