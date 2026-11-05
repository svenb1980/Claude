"""Nightly market data refresh."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def start_scheduler(job, hour: int, timezone: str) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        job,
        CronTrigger(hour=hour, minute=30, timezone=timezone),
        id="nightly-refresh",
        coalesce=True,
        misfire_grace_time=6 * 3600,
        max_instances=1,
    )
    scheduler.start()
    log.info("Nightly refresh scheduled at %02d:30 %s", hour, timezone)
    return scheduler
