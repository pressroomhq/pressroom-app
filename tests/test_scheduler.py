"""T11 — Scheduler & Session lifecycle tests.

Tests that the scheduler can start, sessions don't leak,
and concurrent requests work without DB lock errors.
"""

import asyncio
import pytest


@pytest.mark.asyncio
async def test_scheduler_starts(org_client):
    """T11.1 — Scheduler starts without error."""
    from services.scheduler import check_scheduled_content
    # Just verify it runs without exception
    await check_scheduled_content()


@pytest.mark.asyncio
async def test_session_lifecycle():
    """T11.2 — Session opens and closes cleanly."""
    from database import async_session

    async with async_session() as session:
        from sqlalchemy import text
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    # Session should be closed here — no leaked connections


@pytest.mark.asyncio
async def test_concurrent_requests(org_client):
    """T11.3 — 10 simultaneous requests to different endpoints, no DB lock errors."""
    endpoints = [
        "/api/signals",
        "/api/content",
        "/api/stories",
        "/api/assets",
        "/api/properties",
        "/api/signals",
        "/api/content",
        "/api/stories",
        "/api/assets",
        "/api/properties",
    ]

    async def fetch(url):
        r = await org_client.get(url)
        return r.status_code

    results = await asyncio.gather(*[fetch(url) for url in endpoints])
    assert all(code == 200 for code in results), f"Some requests failed: {results}"


@pytest.mark.asyncio
async def test_scheduler_publishes_due_content():
    """Scheduler finds and processes due scheduled content."""
    import datetime
    from database import async_session
    from models import Content, ContentChannel, ContentStatus
    from services.scheduler import check_scheduled_content

    # Create content scheduled in the past
    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.linkedin,
            status=ContentStatus.approved,
            headline="Scheduled Post",
            body="Auto-publish me",
            scheduled_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=5),
        )
        session.add(c)
        await session.commit()

    # Run scheduler check — it should attempt to publish
    # (will fail gracefully since no social tokens configured)
    await check_scheduled_content()
