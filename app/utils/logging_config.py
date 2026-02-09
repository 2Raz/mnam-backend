"""
Structured Logging Configuration - NFR Implementation

Provides JSON-formatted logging with:
- Request ID tracking
- User context
- Performance metrics
- Structured output for log aggregation
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from contextvars import ContextVar

# Context variables for request tracking
request_id_var: ContextVar[str] = ContextVar('request_id', default='')
user_id_var: ContextVar[str] = ContextVar('user_id', default='')


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    Outputs logs in JSON format for easy parsing by log aggregators.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add request context if available
        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id
            
        user_id = user_id_var.get()
        if user_id:
            log_data["user_id"] = user_id
        
        # Add location info
        log_data["module"] = record.module
        log_data["function"] = record.funcName
        log_data["line"] = record.lineno
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        if hasattr(record, 'extra_data'):
            log_data["data"] = record.extra_data
            
        # Add duration if present (for performance logging)
        if hasattr(record, 'duration_ms'):
            log_data["duration_ms"] = record.duration_ms
            
        # Add entity info if present
        if hasattr(record, 'entity_type'):
            log_data["entity_type"] = record.entity_type
        if hasattr(record, 'entity_id'):
            log_data["entity_id"] = record.entity_id
        
        return json.dumps(log_data, ensure_ascii=False, default=str)


class StructuredLogger(logging.LoggerAdapter):
    """
    Logger adapter that adds structured context to log messages.
    """
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        # Merge extra data
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs
    
    def log_with_context(
        self,
        level: int,
        msg: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **extra_data
    ):
        """Log with additional structured context."""
        extra = {}
        if entity_type:
            extra['entity_type'] = entity_type
        if entity_id:
            extra['entity_id'] = entity_id
        if duration_ms is not None:
            extra['duration_ms'] = duration_ms
        if extra_data:
            extra['extra_data'] = extra_data
            
        self.log(level, msg, extra=extra)
    
    def booking_created(self, booking_id: str, guest_name: str, total_price: float, duration_ms: float = None):
        """Log booking creation with structured data."""
        self.log_with_context(
            logging.INFO,
            f"Booking created: {guest_name}",
            entity_type="booking",
            entity_id=booking_id,
            duration_ms=duration_ms,
            guest_name=guest_name,
            total_price=total_price
        )
    
    def booking_status_changed(self, booking_id: str, old_status: str, new_status: str):
        """Log booking status change."""
        self.log_with_context(
            logging.INFO,
            f"Booking status changed: {old_status} → {new_status}",
            entity_type="booking",
            entity_id=booking_id,
            old_status=old_status,
            new_status=new_status
        )
    
    def api_request(self, method: str, path: str, status_code: int, duration_ms: float):
        """Log API request with performance data."""
        self.log_with_context(
            logging.INFO,
            f"{method} {path} - {status_code}",
            duration_ms=duration_ms,
            method=method,
            path=path,
            status_code=status_code
        )


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    include_uvicorn: bool = True
) -> None:
    """
    Configure application logging.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use JSON format (True for production)
        include_uvicorn: Also configure uvicorn loggers
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    # Use JSON formatter for production, simple for development
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]
    
    # Configure app logger
    app_logger = logging.getLogger("app")
    app_logger.setLevel(log_level)
    
    # Configure uvicorn loggers
    if include_uvicorn:
        for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.handlers = [handler]
    
    # Reduce noise from third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger for the given module."""
    base_logger = logging.getLogger(name)
    return StructuredLogger(base_logger, {})


# Convenience function for setting request context
def set_request_context(request_id: str, user_id: Optional[str] = None):
    """Set context for the current request."""
    request_id_var.set(request_id)
    if user_id:
        user_id_var.set(user_id)


def clear_request_context():
    """Clear request context."""
    request_id_var.set('')
    user_id_var.set('')
