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
        ), {"now": datetime.datetime.utcnow().isoformat()})
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


async def scheduler_loop():
    """Run the scheduler check every 60 seconds."""
    log.info("[scheduler] Background scheduler started — checking every 60s")
    perf_counter = 0
    while True:
        try:
            await check_scheduled_content()
        except Exception as e:
            log.error("[scheduler] Scheduler loop error: %s", e)

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
