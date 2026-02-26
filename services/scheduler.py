"""Scheduler — background loop that publishes content when scheduled_at is due.

Simple asyncio loop, checks every 60 seconds. No external scheduling library needed.
All times are UTC.
"""

import asyncio
import datetime
import logging

from sqlalchemy import text

from database import async_session
from services.data_layer import DataLayer
from services.publisher import publish_single

log = logging.getLogger("pressroom")


async def check_scheduled_content():
    """Check for content that's due to be published and publish it."""
    async with async_session() as session:
        # Find all approved content where scheduled_at has passed
        result = await session.execute(text(
            "SELECT id, org_id FROM content "
            "WHERE status = 'approved' AND scheduled_at IS NOT NULL AND scheduled_at <= :now"
        ), {"now": datetime.datetime.utcnow()})
        rows = result.fetchall()

        if rows:
            log.info("[scheduler] Found %d scheduled items due for publishing", len(rows))
        for row in rows:
            content_id, org_id = row
            try:
                org_dl = DataLayer(session, org_id=org_id)
                content = await org_dl.get_content(content_id)
                if not content:
                    continue
                settings = await org_dl.get_all_settings()
                pub_result = await publish_single(content, settings)
                if pub_result.get("success") or pub_result.get("status") == "no_destination":
                    extra = {}
                    pid = pub_result.get("id") or pub_result.get("post_id") or ""
                    purl = pub_result.get("url") or pub_result.get("devto_url") or ""
                    if pid:
                        extra["post_id"] = str(pid)
                    if purl:
                        extra["post_url"] = str(purl)
                    await org_dl.update_content_status(content_id, "published", **extra)
                    log.info("SCHEDULER — published content #%s (org=%s, post_id=%s)", content_id, org_id, pid)
                await org_dl.commit()
            except Exception as e:
                log.error("SCHEDULER — failed to publish #%s: %s", content_id, e)


async def run_global_sweep():
    """Run the SIGINT global sweep — crawls all active sources, embeds, deduplicates.

    Sources with fetch_interval_hours > 1 are skipped if crawled recently.
    Safe to call every hour — each source decides its own cadence.
    """
    from models import Source
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(Source).where(Source.active == True)
        )
        sources = result.scalars().all()

    # Filter to sources that are due for a refresh
    due = []
    now = datetime.datetime.utcnow()
    for src in sources:
        if src.last_fetched_at is None:
            due.append(src.id)
        else:
            interval_hours = getattr(src, "fetch_interval_hours", 24) or 24
            age_hours = (now - src.last_fetched_at).total_seconds() / 3600
            if age_hours >= interval_hours:
                due.append(src.id)

    if not due:
        log.info("[scheduler] SWEEP — all sources up to date, skipping")
        return

    log.info("[scheduler] SWEEP — %d sources due for refresh", len(due))
    try:
        from services.sweep import run_sweep
        result = await run_sweep(source_ids=due)
        log.info("[scheduler] SWEEP — complete: %d new signals across %d sources",
                 result["total_new"], result["swept"])
    except Exception as e:
        log.error("[scheduler] SWEEP — failed: %s", e)


async def scheduler_loop():
    """Run the scheduler check every 60 seconds."""
    log.info("[scheduler] Background scheduler started — checking every 60s")
    perf_counter = 0
    sweep_counter = 0
    while True:
        try:
            await check_scheduled_content()
        except Exception as e:
            log.error("[scheduler] Scheduler loop error: %s", e)

        # Run global SIGINT sweep every hour (every 60th loop)
        sweep_counter += 1
        if sweep_counter >= 60:
            sweep_counter = 0
            try:
                await run_global_sweep()
            except Exception as e:
                log.error("[scheduler] Sweep loop error: %s", e)

        # Fetch performance metrics every 15 minutes (every 15th loop)
        perf_counter += 1
        if perf_counter >= 15:
            perf_counter = 0
            try:
                from services.performance import fetch_all_performance
                await fetch_all_performance()
            except Exception as e:
                log.error("[scheduler] Performance fetch error: %s", e)

        await asyncio.sleep(60)
