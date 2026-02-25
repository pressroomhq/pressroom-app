"""T8 — Analytics (raw SQL queries).

The analytics dashboard uses raw SQL for aggregation queries.
These tests verify the queries execute without SQL errors on PostgreSQL.
"""

import pytest


@pytest.mark.asyncio
async def test_dashboard_basic(org_client):
    """T8.1 — GET /api/analytics/dashboard returns 200, not 500."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "signals" in data
    assert "content" in data
    assert "pipeline" in data
    assert "approval_rate" in data


@pytest.mark.asyncio
async def test_dashboard_signal_counts(org_client):
    """T8.2 — Signal counts include by_day (last 7 days DATE query)."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "by_day" in data["signals"]
    assert isinstance(data["signals"]["by_day"], dict)


@pytest.mark.asyncio
async def test_dashboard_with_data(org_client, test_org_id):
    """T8.3 — Dashboard with signals returns correct counts."""
    # Create a signal first
    from database import async_session
    from models import Signal, SignalType
    async with async_session() as session:
        sig = Signal(
            org_id=test_org_id,
            type=SignalType.hackernews,
            source="Hacker News",
            title="Test HN Signal",
            body="Some HN post body",
        )
        session.add(sig)
        await session.commit()

    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["signals"]["total"] >= 1


@pytest.mark.asyncio
async def test_dashboard_content_by_status(org_client):
    """T8.4 — Content breakdown by status."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "by_status" in data["content"]
    assert isinstance(data["content"]["by_status"], dict)


@pytest.mark.asyncio
async def test_dashboard_content_by_channel(org_client):
    """T8.5 — Content breakdown by channel."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "by_channel" in data["content"]
    assert isinstance(data["content"]["by_channel"], dict)


@pytest.mark.asyncio
async def test_dashboard_approval_rate(org_client):
    """Approval rate is a float 0-100."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    rate = data["approval_rate"]
    assert isinstance(rate, (int, float))
    assert 0 <= rate <= 100


@pytest.mark.asyncio
async def test_dashboard_top_signals(org_client):
    """Top signals list is returned."""
    r = await org_client.get("/api/analytics/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "top_signals" in data
    assert isinstance(data["top_signals"], list)
    assert "top_spiked" in data
    assert isinstance(data["top_spiked"], list)
