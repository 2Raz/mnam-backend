"""
Price Scheduler Service

Automatically syncs prices to Channex at discount time boundaries:
- 00:00: Full price (no discount)
- 16:00: discount_16_percent
- 21:00: discount_21_percent
- 23:00: discount_23_percent

Uses APScheduler for cron-based scheduling.
"""

import logging
from datetime import datetime
from typing import Dict, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..database import SessionLocal
from ..models.channel_integration import (
    ChannelConnection,
    ExternalMapping,
    ConnectionStatus
)
from ..models.unit import Unit
from .outbox_worker import enqueue_price_update

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None
_last_sync_time: Optional[datetime] = None
_last_sync_result: Optional[Dict] = None

# Timezone for Saudi Arabia
SCHEDULER_TIMEZONE = "Asia/Riyadh"


def sync_prices_at_discount_time(db: Session) -> Dict:
    """
    Sync prices for all units with active Channex mappings.
    
    This function:
    1. Finds all units with active channel connections
    2. Enqueues a price update for each unit
    3. Returns a summary of the sync
    
    Returns:
        Dict with keys: units_synced, connections_checked, errors
    """
    global _last_sync_time, _last_sync_result
    
    result = {
        "units_synced": 0,
        "connections_checked": 0,
        "errors": [],
        "sync_time": datetime.utcnow().isoformat()
    }
    
    try:
        # Get all active channel connections
        connections = db.query(ChannelConnection).filter(
            and_(
                ChannelConnection.status == ConnectionStatus.ACTIVE.value,
                ChannelConnection.deleted_at.is_(None)
            )
        ).all()
        
        result["connections_checked"] = len(connections)
        
        for connection in connections:
            # Get all active mappings for this connection
            mappings = db.query(ExternalMapping).filter(
                and_(
                    ExternalMapping.connection_id == connection.id,
                    ExternalMapping.is_active == True,
                    ExternalMapping.channex_rate_plan_id.isnot(None)
                )
            ).all()
            
            for mapping in mappings:
                try:
                    # Enqueue price update for this unit
                    idempotency_key = f"scheduled_price_{mapping.unit_id}_{datetime.utcnow().strftime('%Y%m%d%H')}"
                    enqueue_price_update(
                        db=db,
                        unit_id=mapping.unit_id,
                        connection_id=connection.id,
                        idempotency_key=idempotency_key
                    )
                    result["units_synced"] += 1
                except Exception as e:
                    error_msg = f"Failed to enqueue unit {mapping.unit_id}: {str(e)}"
                    logger.error(error_msg)
                    result["errors"].append(error_msg)
        
        _last_sync_time = datetime.utcnow()
        _last_sync_result = result
        
        logger.info(
            f"Price sync completed: {result['units_synced']} units, "
            f"{result['connections_checked']} connections"
        )
        
    except Exception as e:
        error_msg = f"Price sync failed: {str(e)}"
        logger.error(error_msg)
        result["errors"].append(error_msg)
    
    return result


async def run_price_scheduler_job():
    """
    Async job function called by the scheduler.
    
    Creates a database session, runs the sync, and cleans up.
    """
    logger.info("Running scheduled price sync job...")
    
    db = SessionLocal()
    try:
        result = sync_prices_at_discount_time(db)
        logger.info(f"Scheduled sync result: {result}")
    except Exception as e:
        logger.error(f"Scheduled price sync job failed: {e}")
    finally:
        db.close()


def start_price_scheduler() -> bool:
    """
    Start the price scheduler with jobs at 00:00, 16:00, 21:00, 23:00.
    
    Returns:
        True if scheduler started successfully, False otherwise
    """
    global _scheduler
    
    if _scheduler is not None and _scheduler.running:
        logger.warning("Price scheduler is already running")
        return True
    
    try:
        _scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        
        # Add job for 00:00 - Full price (no discount)
        _scheduler.add_job(
            run_price_scheduler_job,
            CronTrigger(hour=0, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="price_sync_00",
            name="Price Sync at 00:00 (Full Price)",
            replace_existing=True
        )
        
        # Add job for 16:00 - discount_16_percent
        _scheduler.add_job(
            run_price_scheduler_job,
            CronTrigger(hour=16, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="price_sync_16",
            name="Price Sync at 16:00 (Discount 16)",
            replace_existing=True
        )
        
        # Add job for 21:00 - discount_21_percent
        _scheduler.add_job(
            run_price_scheduler_job,
            CronTrigger(hour=21, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="price_sync_21",
            name="Price Sync at 21:00 (Discount 21)",
            replace_existing=True
        )
        
        # Add job for 23:00 - discount_23_percent
        _scheduler.add_job(
            run_price_scheduler_job,
            CronTrigger(hour=23, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="price_sync_23",
            name="Price Sync at 23:00 (Discount 23)",
            replace_existing=True
        )
        
        _scheduler.start()
        
        logger.info(
            f"📅 Price Scheduler started (next runs: 00:00, 16:00, 21:00, 23:00 {SCHEDULER_TIMEZONE})"
        )
        return True
        
    except Exception as e:
        logger.error(f"Failed to start price scheduler: {e}")
        return False


def stop_price_scheduler() -> bool:
    """
    Stop the price scheduler gracefully.
    
    Returns:
        True if scheduler stopped successfully, False otherwise
    """
    global _scheduler
    
    if _scheduler is None:
        logger.warning("Price scheduler is not running")
        return True
    
    try:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("📅 Price Scheduler stopped")
        return True
    except Exception as e:
        logger.error(f"Failed to stop price scheduler: {e}")
        return False


def get_scheduler_status() -> Dict:
    """
    Get the current status of the price scheduler.
    
    Returns:
        Dict with scheduler status information
    """
    global _scheduler, _last_sync_time, _last_sync_result
    
    status = {
        "running": False,
        "next_runs": [],
        "timezone": SCHEDULER_TIMEZONE,
        "last_sync": None,
        "last_sync_result": None,
        "jobs": []
    }
    
    if _scheduler is not None and _scheduler.running:
        status["running"] = True
        
        # Get next run times for each job
        jobs = _scheduler.get_jobs()
        for job in jobs:
            job_info = {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            }
            status["jobs"].append(job_info)
            if job.next_run_time:
                status["next_runs"].append(job.next_run_time.strftime("%H:%M"))
        
        # Sort next runs
        status["next_runs"].sort()
    
    if _last_sync_time:
        status["last_sync"] = _last_sync_time.isoformat()
    
    if _last_sync_result:
        status["last_sync_result"] = _last_sync_result
    
    return status


def trigger_manual_sync() -> Dict:
    """
    Trigger a manual price sync immediately.
    
    Used by the API endpoint for manual control.
    
    Returns:
        Dict with sync result
    """
    db = SessionLocal()
    try:
        result = sync_prices_at_discount_time(db)
        return result
    finally:
        db.close()
