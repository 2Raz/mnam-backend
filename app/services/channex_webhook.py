"""
Channex Webhook Handler (Legacy)

NOTE: This module is deprecated. Use webhook_processor.py instead.

The new async pattern:
1. AsyncWebhookReceiver - Fast path, persists raw event, returns 200 immediately
2. WebhookProcessor - Async path, processes events via worker

This file is kept for backwards compatibility but imports from webhook_processor.
"""

import warnings

# Emit deprecation warning
warnings.warn(
    "channex_webhook.py is deprecated. Use webhook_processor.py instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new module for backwards compatibility
from .webhook_processor import (
    AsyncWebhookReceiver,
    WebhookProcessor,
    WebhookReceiveResult,
    WebhookProcessResult
)

# Alias for backwards compatibility
ChannexWebhookHandler = WebhookProcessor

__all__ = [
    "ChannexWebhookHandler",
    "AsyncWebhookReceiver", 
    "WebhookProcessor",
    "WebhookReceiveResult",
    "WebhookProcessResult"
]
