"""Performance tracker — fetches post-publish engagement metrics.

Runs periodically from the scheduler. Fetches stats from LinkedIn, Dev.to,
and Facebook for recently published content, stores snapshots in
content_performance table.
"""

import datetime
import logging

from sqlalchemy import select, text

from database import async_session
from models import Content, ContentPerformance, ContentStatus
from services.data_layer import DataLayer
from services import social_auth

log = logging.getLogger("pressroom")


async def fetch_performance_for_org(org_id: int):
    """Fetch performance metrics for all published content with post_ids in an org."""
    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        # Find published content with post_ids from the last 30 days
        result = await session.execute(
            select(Content).where(
                Content.org_id == org_id,
                Content.status == ContentStatus.published,
                Content.post_id != "",
                Content.post_id.isnot(None),
                Content.published_at >= datetime.datetime.utcnow() - datetime.timedelta(days=30),
            )
        )
        items = result.scalars().all()

        if not items:
            return 0

        log.info("[performance] Fetching metrics for %d published items (org=%s)", len(items), org_id)
        fetched = 0

        for content in items:
            stats = {}
            channel = content.channel.value if content.channel else ""

            try:
                if channel == "linkedin":
                    token = settings.get("linkedin_access_token", "")
                    if token and content.post_id:
                        stats = await social_auth.linkedin_post_stats(token, content.post_id)

                elif channel == "devto":
                    api_key = settings.get("devto_api_key", "")
                    if api_key and content.post_id:
                        stats = await social_auth.devto_post_stats(api_key, content.post_id)

                elif channel == "facebook":
                    page_token = settings.get("facebook_page_token", "")
                    if page_token and content.post_id:
                        stats = await social_auth.facebook_post_stats(page_token, content.post_id)

            except Exception as e:
                log.warning("[performance] Failed to fetch stats for content #%s (%s): %s",
                            content.id, channel, e)
                continue

            if stats and any(v > 0 for v in stats.values()):
                perf = ContentPerformance(
                    content_id=content.id,
                    impressions=stats.get("impressions", 0),
                    clicks=stats.get("clicks", 0),
                    likes=stats.get("likes", 0),
                    comments=stats.get("comments", 0),
                    shares=stats.get("shares", 0),
                    fetched_at=datetime.datetime.utcnow(),
                )
                session.add(perf)
                fetched += 1
                log.info("[performance] %s #%s — likes=%d comments=%d shares=%d",
                         channel, content.id, stats.get("likes", 0),
                         stats.get("comments", 0), stats.get("shares", 0))

        if fetched:
            await session.commit()
        log.info("[performance] Org %s — %d/%d items had new metrics", org_id, fetched, len(items))
        return fetched


async def fetch_all_performance():
    """Fetch performance metrics across all orgs with published content."""
    async with async_session() as session:
        result = await session.execute(text(
            "SELECT DISTINCT org_id FROM content "
            "WHERE status = 'published' AND post_id != '' AND post_id IS NOT NULL "
            "AND published_at >= :cutoff"
        ), {"cutoff": datetime.datetime.utcnow() - datetime.timedelta(days=30)})
        org_ids = [row[0] for row in result.fetchall() if row[0]]

    if not org_ids:
        return

    log.info("[performance] Checking performance for %d orgs", len(org_ids))
    total = 0
    for org_id in org_ids:
        try:
            total += await fetch_performance_for_org(org_id)
        except Exception as e:
            log.error("[performance] Failed for org %s: %s", org_id, e)

    if total:
        log.info("[performance] Total: %d new performance snapshots saved", total)
