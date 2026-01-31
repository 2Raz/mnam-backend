#!/usr/bin/env python
"""
Integration Worker

Background process that:
1. Processes outbox events (push to Channex)
2. Processes pending webhooks (booking creation)

Run with:
    python worker.py

Or with environment:
    WORKER_INTERVAL=10 python worker.py
"""

import os
import sys
import time
import logging
import signal
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.services.outbox_worker import OutboxProcessor
from app.services.webhook_processor import WebhookProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("worker")

# Worker configuration
POLL_INTERVAL = int(os.getenv("WORKER_INTERVAL", "10"))  # seconds
BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "50"))
RUNNING = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global RUNNING
    logger.info("Received shutdown signal, finishing current batch...")
    RUNNING = False


def process_outbox(db):
    """Process pending outbox events"""
    try:
        processor = OutboxProcessor(db)
        
        # Get pending events and merge overlapping ones
        events = processor.get_pending_events(limit=BATCH_SIZE)
        events = processor.merge_overlapping_events(events)
        
        if not events:
            return 0, 0
        
        success = 0
        failed = 0
        
        for event in events:
            try:
                if processor.process_event(event):
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Error processing event {event.id}: {e}")
                failed += 1
        
        return success, failed
        
    except Exception as e:
        logger.error(f"Error in outbox processing: {e}")
        return 0, 0


def process_webhooks(db):
    """Process pending webhook events"""
    try:
        processor = WebhookProcessor(db)
        success, failed = processor.process_batch(limit=BATCH_SIZE)
        return success, failed
        
    except Exception as e:
        logger.error(f"Error in webhook processing: {e}")
        return 0, 0


def run_worker():
    """Main worker loop"""
    logger.info("=" * 50)
    logger.info("Starting Integration Worker")
    logger.info(f"Poll interval: {POLL_INTERVAL}s")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info("=" * 50)
    
    cycle = 0
    
    while RUNNING:
        cycle += 1
        start_time = time.time()
        
        db = SessionLocal()
        try:
            # Process outbox (push to Channex)
            outbox_success, outbox_failed = process_outbox(db)
            
            # Process webhooks (bookings from Channex)
            webhook_success, webhook_failed = process_webhooks(db)
            
            # Log results (only if something happened)
            if outbox_success + outbox_failed + webhook_success + webhook_failed > 0:
                duration = time.time() - start_time
                logger.info(
                    f"Cycle {cycle}: "
                    f"Outbox {outbox_success}✓/{outbox_failed}✗ | "
                    f"Webhooks {webhook_success}✓/{webhook_failed}✗ | "
                    f"{duration:.2f}s"
                )
            
        except Exception as e:
            logger.error(f"Critical error in cycle {cycle}: {e}")
            
        finally:
            db.close()
        
        # Sleep until next poll
        if RUNNING:
            time.sleep(POLL_INTERVAL)
    
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        run_worker()
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.critical(f"Worker crashed: {e}")
        sys.exit(1)
