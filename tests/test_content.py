"""T5 — Content CRUD + status transitions."""

import pytest

from database import async_session
from models import Content, ContentChannel, ContentStatus


async def _create_content(org_id: int):
    """Helper: create content directly in DB for the given org."""
    async with async_session() as session:
        c = Content(
            org_id=org_id,
            channel=ContentChannel.linkedin,
            status=ContentStatus.queued,
            headline="Test Content Headline",
            body="Test content body for LinkedIn post.",
        )
        session.add(c)
        await session.flush()
        content_id = c.id
        await session.commit()
        return content_id


@pytest.mark.asyncio
async def test_list_empty(org_client):
    """T5.1 — Empty org returns empty list."""
    r = await org_client.get("/api/content")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_content(org_client, test_org_id):
    """T5.3 — Content appears in list after creation."""
    content_id = await _create_content(test_org_id)
    r = await org_client.get("/api/content")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_get_content(org_client, test_org_id):
    """T5.3 — Fetch content by ID."""
    content_id = await _create_content(test_org_id)
    r = await org_client.get(f"/api/content/{content_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["headline"] == "Test Content Headline"


@pytest.mark.asyncio
async def test_get_content_not_found(org_client):
    """Content not found returns 404."""
    r = await org_client.get("/api/content/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_queue_endpoint(org_client, test_org_id):
    """T5.6 — Queue returns queued content."""
    await _create_content(test_org_id)
    r = await org_client.get("/api/content/queue")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_approve_action(org_client, test_org_id):
    """T5.7 — Status transition: queued -> approved."""
    content_id = await _create_content(test_org_id)
    r = await org_client.post(
        f"/api/content/{content_id}/action",
        json={"action": "approve"},
    )
    assert r.status_code == 200

    # Verify status changed
    r2 = await org_client.get(f"/api/content/{content_id}")
    assert r2.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_spike_action(org_client, test_org_id):
    """Status transition: queued -> spiked."""
    content_id = await _create_content(test_org_id)
    r = await org_client.post(
        f"/api/content/{content_id}/action",
        json={"action": "spike"},
    )
    assert r.status_code == 200

    r2 = await org_client.get(f"/api/content/{content_id}")
    assert r2.json()["status"] == "spiked"


@pytest.mark.asyncio
async def test_unknown_action(org_client, test_org_id):
    """Unknown action returns 400."""
    content_id = await _create_content(test_org_id)
    r = await org_client.post(
        f"/api/content/{content_id}/action",
        json={"action": "invalid_action"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_schedule_content(org_client, test_org_id):
    """Schedule approved content for future publishing."""
    content_id = await _create_content(test_org_id)
    # Approve first
    await org_client.post(f"/api/content/{content_id}/action", json={"action": "approve"})

    r = await org_client.post(
        f"/api/content/{content_id}/schedule",
        json={"scheduled_at": "2026-12-31T12:00:00"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_schedule_invalid_date(org_client, test_org_id):
    """Invalid datetime returns 400."""
    content_id = await _create_content(test_org_id)
    r = await org_client.post(
        f"/api/content/{content_id}/schedule",
        json={"scheduled_at": "not-a-date"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_scheduled(org_client):
    """Scheduled content endpoint returns 200."""
    r = await org_client.get("/api/content/scheduled")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_published_performance(org_client):
    """Published performance endpoint returns dict."""
    r = await org_client.get("/api/content/published/performance")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


@pytest.mark.asyncio
async def test_content_filter_by_status(org_client, test_org_id):
    """Filter content by status query param."""
    await _create_content(test_org_id)
    r = await org_client.get("/api/content?status=queued")
    assert r.status_code == 200
    for item in r.json():
        assert item["status"] == "queued"
