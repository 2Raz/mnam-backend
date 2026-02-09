"""
Prometheus Metrics - NFR Implementation

Provides application metrics in Prometheus format:
- HTTP request metrics (count, duration, status codes)
- Business metrics (bookings, revenue, etc.)
- System metrics (connections, queue sizes)
"""

from typing import Dict, Optional
from datetime import datetime
import time
from collections import defaultdict
from threading import Lock


class Counter:
    """Simple counter metric."""
    
    def __init__(self, name: str, description: str, labels: tuple = ()):
        self.name = name
        self.description = description
        self.labels = labels
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = Lock()
    
    def inc(self, value: float = 1, **label_values):
        """Increment counter."""
        key = tuple(label_values.get(l, '') for l in self.labels)
        with self._lock:
            self._values[key] += value
    
    def get_all(self) -> Dict[tuple, float]:
        """Get all values."""
        with self._lock:
            return dict(self._values)


class Gauge:
    """Simple gauge metric (can go up and down)."""
    
    def __init__(self, name: str, description: str, labels: tuple = ()):
        self.name = name
        self.description = description
        self.labels = labels
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = Lock()
    
    def set(self, value: float, **label_values):
        """Set gauge value."""
        key = tuple(label_values.get(l, '') for l in self.labels)
        with self._lock:
            self._values[key] = value
    
    def inc(self, value: float = 1, **label_values):
        """Increment gauge."""
        key = tuple(label_values.get(l, '') for l in self.labels)
        with self._lock:
            self._values[key] += value
    
    def dec(self, value: float = 1, **label_values):
        """Decrement gauge."""
        key = tuple(label_values.get(l, '') for l in self.labels)
        with self._lock:
            self._values[key] -= value
    
    def get_all(self) -> Dict[tuple, float]:
        """Get all values."""
        with self._lock:
            return dict(self._values)


class Histogram:
    """Simple histogram metric."""
    
    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf'))
    
    def __init__(self, name: str, description: str, labels: tuple = (), buckets: tuple = None):
        self.name = name
        self.description = description
        self.labels = labels
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts: Dict[tuple, Dict[float, int]] = defaultdict(lambda: defaultdict(int))
        self._sums: Dict[tuple, float] = defaultdict(float)
        self._totals: Dict[tuple, int] = defaultdict(int)
        self._lock = Lock()
    
    def observe(self, value: float, **label_values):
        """Record an observation."""
        key = tuple(label_values.get(l, '') for l in self.labels)
        with self._lock:
            self._sums[key] += value
            self._totals[key] += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[key][bucket] += 1
    
    def time(self, **label_values):
        """Context manager to time a block of code."""
        return _HistogramTimer(self, label_values)
    
    def get_all(self) -> Dict:
        """Get all values."""
        with self._lock:
            return {
                'counts': dict(self._counts),
                'sums': dict(self._sums),
                'totals': dict(self._totals)
            }


class _HistogramTimer:
    """Context manager for timing code blocks."""
    
    def __init__(self, histogram: Histogram, label_values: dict):
        self.histogram = histogram
        self.label_values = label_values
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.perf_counter() - self.start_time
        self.histogram.observe(duration, **self.label_values)


# ================================
# APPLICATION METRICS
# ================================

# HTTP Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labels=("method", "path", "status_code")
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labels=("method", "path")
)

# Business Metrics
bookings_total = Counter(
    "bookings_total",
    "Total bookings created",
    labels=("status", "channel_source")
)

bookings_by_status = Gauge(
    "bookings_by_status",
    "Current bookings by status",
    labels=("status",)
)

revenue_total = Counter(
    "revenue_total",
    "Total revenue from bookings",
    labels=("channel_source",)
)

# Channex Integration Metrics
channex_sync_total = Counter(
    "channex_sync_total",
    "Channex sync operations",
    labels=("operation", "status")
)

channex_sync_duration_seconds = Histogram(
    "channex_sync_duration_seconds",
    "Channex sync duration in seconds",
    labels=("operation",)
)

webhook_events_total = Counter(
    "webhook_events_total",
    "Webhook events received",
    labels=("event_type", "status")
)

# System Metrics
active_connections = Gauge(
    "active_connections",
    "Active database connections"
)

outbox_queue_size = Gauge(
    "outbox_queue_size",
    "Size of the outbox queue"
)


def format_prometheus_metrics() -> str:
    """Format all metrics in Prometheus text format."""
    lines = []
    timestamp = int(time.time() * 1000)
    
    # Helper to format metric line
    def add_metric(name: str, value: float, labels: dict = None, help_text: str = None, metric_type: str = None):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        if metric_type:
            lines.append(f"# TYPE {name} {metric_type}")
        
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    
    # HTTP Request Counter
    add_metric("http_requests_total", 0, help_text=http_requests_total.description, metric_type="counter")
    for key, value in http_requests_total.get_all().items():
        labels = dict(zip(http_requests_total.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'http_requests_total{{{label_str}}} {value}')
    
    # HTTP Duration Histogram
    hist_data = http_request_duration_seconds.get_all()
    add_metric("http_request_duration_seconds", 0, help_text=http_request_duration_seconds.description, metric_type="histogram")
    for key in hist_data['sums'].keys():
        labels = dict(zip(http_request_duration_seconds.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k,v in labels.items())
        lines.append(f'http_request_duration_seconds_sum{{{label_str}}} {hist_data["sums"][key]}')
        lines.append(f'http_request_duration_seconds_count{{{label_str}}} {hist_data["totals"][key]}')
    
    # Bookings Counter
    add_metric("bookings_total", 0, help_text=bookings_total.description, metric_type="counter")
    for key, value in bookings_total.get_all().items():
        labels = dict(zip(bookings_total.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'bookings_total{{{label_str}}} {value}')
    
    # Bookings by Status Gauge
    add_metric("bookings_by_status", 0, help_text=bookings_by_status.description, metric_type="gauge")
    for key, value in bookings_by_status.get_all().items():
        labels = dict(zip(bookings_by_status.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'bookings_by_status{{{label_str}}} {value}')
    
    # Revenue Counter
    add_metric("revenue_total", 0, help_text=revenue_total.description, metric_type="counter")
    for key, value in revenue_total.get_all().items():
        labels = dict(zip(revenue_total.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'revenue_total{{{label_str}}} {value}')
    
    # Channex Sync Counter
    add_metric("channex_sync_total", 0, help_text=channex_sync_total.description, metric_type="counter")
    for key, value in channex_sync_total.get_all().items():
        labels = dict(zip(channex_sync_total.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'channex_sync_total{{{label_str}}} {value}')
    
    # Webhook Events Counter
    add_metric("webhook_events_total", 0, help_text=webhook_events_total.description, metric_type="counter")
    for key, value in webhook_events_total.get_all().items():
        labels = dict(zip(webhook_events_total.labels, key))
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f'webhook_events_total{{{label_str}}} {value}')
    
    # System Gauges
    add_metric("active_connections", 0, help_text=active_connections.description, metric_type="gauge")
    for key, value in active_connections.get_all().items():
        lines.append(f'active_connections {value}')
    
    add_metric("outbox_queue_size", 0, help_text=outbox_queue_size.description, metric_type="gauge")
    for key, value in outbox_queue_size.get_all().items():
        lines.append(f'outbox_queue_size {value}')
    
    return "\n".join(lines)


# ================================
# CONVENIENCE FUNCTIONS
# ================================

def record_http_request(method: str, path: str, status_code: int, duration: float):
    """Record an HTTP request."""
    http_requests_total.inc(method=method, path=path, status_code=str(status_code))
    http_request_duration_seconds.observe(duration, method=method, path=path)


def record_booking_created(status: str, channel_source: str, total_price: float):
    """Record a new booking."""
    bookings_total.inc(status=status, channel_source=channel_source)
    revenue_total.inc(total_price, channel_source=channel_source)


def record_channex_sync(operation: str, success: bool, duration: float):
    """Record a Channex sync operation."""
    status = "success" if success else "error"
    channex_sync_total.inc(operation=operation, status=status)
    channex_sync_duration_seconds.observe(duration, operation=operation)


def record_webhook_event(event_type: str, success: bool):
    """Record a webhook event."""
    status = "success" if success else "error"
    webhook_events_total.inc(event_type=event_type, status=status)
