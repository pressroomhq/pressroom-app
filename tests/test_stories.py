"""T6 — Stories CRUD."""

import pytest


@pytest.mark.asyncio
async def test_list_empty(org_client):
    """T6.1 — Empty org returns empty list."""
    r = await org_client.get("/api/stories")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_story(org_client):
    """T6.2 — Create story."""
    r = await org_client.post(
        "/api/stories",
        json={"title": "Test Story", "angle": "Focus on developer experience"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["title"] == "Test Story"


@pytest.mark.asyncio
async def test_get_story(org_client):
    """T6.3 — Fetch story by ID."""
    r = await org_client.post(
        "/api/stories",
        json={"title": "Fetchable Story"},
    )
    story_id = r.json()["id"]

    r2 = await org_client.get(f"/api/stories/{story_id}")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Fetchable Story"


@pytest.mark.asyncio
async def test_update_story(org_client):
    """T6.4 — Update story title."""
    r = await org_client.post("/api/stories", json={"title": "Original Title"})
    story_id = r.json()["id"]

    r2 = await org_client.put(
        f"/api/stories/{story_id}",
        json={"title": "Updated Title"},
    )
    assert r2.status_code == 200
    assert r2.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_delete_story(org_client):
    """T6.5 — Delete story."""
    r = await org_client.post("/api/stories", json={"title": "Delete Me"})
    story_id = r.json()["id"]

    r2 = await org_client.delete(f"/api/stories/{story_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == story_id

    # Verify gone
    r3 = await org_client.get("/api/stories")
    assert not any(s["id"] == story_id for s in r3.json())


@pytest.mark.asyncio
async def test_story_with_signals(org_client, test_org_id):
    """Create story with signal IDs attached."""
    from database import async_session
    from models import Signal, SignalType

    # Create a signal first
    async with async_session() as session:
        sig = Signal(org_id=test_org_id, type=SignalType.hackernews, source="HN", title="HN Post")
        session.add(sig)
        await session.commit()
        sig_id = sig.id

    r = await org_client.post(
        "/api/stories",
        json={"title": "Story With Signal", "signal_ids": [sig_id]},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("signals", [])) >= 1


@pytest.mark.asyncio
async def test_add_remove_signal(org_client, test_org_id):
    """Add and remove signal from story."""
    from database import async_session
    from models import Signal, SignalType

    async with async_session() as session:
        sig = Signal(org_id=test_org_id, type=SignalType.rss, source="RSS", title="RSS Signal")
        session.add(sig)
        await session.commit()
        sig_id = sig.id

    # Create story
    r = await org_client.post("/api/stories", json={"title": "Signal Mgmt"})
    story_id = r.json()["id"]

    # Add signal
    r2 = await org_client.post(
        f"/api/stories/{story_id}/signals",
        json={"signal_id": sig_id},
    )
    assert r2.status_code == 200
    story_signal_id = r2.json().get("id")

    # Remove signal
    r3 = await org_client.delete(f"/api/stories/{story_id}/signals/{story_signal_id}")
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_story_content(org_client):
    """GET /stories/{id}/content returns list."""
    r = await org_client.post("/api/stories", json={"title": "Content Story"})
    story_id = r.json()["id"]

    r2 = await org_client.get(f"/api/stories/{story_id}/content")
    assert r2.status_code == 200
    assert isinstance(r2.json(), list)
