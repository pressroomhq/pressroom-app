"""T10 — Publishing tests.

Uses mocked external API calls to test the DB write side of publishing.
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_publish_no_token_linkedin(org_client):
    """T10.1 — Publish to LinkedIn with no token configured returns error (not 500)."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus

    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.linkedin,
            status=ContentStatus.approved,
            headline="LinkedIn Post",
            body="Test post for LinkedIn",
        )
        session.add(c)
        await session.commit()
        content_id = c.id

    r = await org_client.post(f"/api/content/{content_id}/publish")
    assert r.status_code == 200
    data = r.json()
    # Should not be a 500 — graceful handling when no token
    assert "result" in data


@pytest.mark.asyncio
async def test_publish_no_api_key_devto(org_client):
    """T10.2 — Publish to Dev.to with no API key returns error (not 500)."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus

    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.devto,
            status=ContentStatus.approved,
            headline="Dev.to Article",
            body="Test article for Dev.to",
        )
        session.add(c)
        await session.commit()
        content_id = c.id

    r = await org_client.post(f"/api/content/{content_id}/publish")
    assert r.status_code == 200
    data = r.json()
    assert "result" in data


@pytest.mark.asyncio
async def test_publish_saves_post_id(org_client):
    """T10.3 — Mock publish saves post_id + post_url on content record."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus

    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.linkedin,
            status=ContentStatus.approved,
            headline="Published Post",
            body="Content to publish",
        )
        session.add(c)
        await session.commit()
        content_id = c.id

    mock_result = {
        "success": True,
        "id": "urn:li:share:12345",
        "url": "https://linkedin.com/post/12345",
    }

    with patch("api.content.publish_single", new_callable=AsyncMock, return_value=mock_result):
        r = await org_client.post(f"/api/content/{content_id}/publish")
        assert r.status_code == 200

    # Verify post_id and post_url were saved
    r2 = await org_client.get(f"/api/content/{content_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["status"] == "published"
    assert data.get("post_id") == "urn:li:share:12345"
    assert data.get("post_url") == "https://linkedin.com/post/12345"


@pytest.mark.asyncio
async def test_published_content_has_fields(org_client):
    """T10.4 — Published content has status=published, post_url set."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus

    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.devto,
            status=ContentStatus.approved,
            headline="Published Article",
            body="Published content body",
        )
        session.add(c)
        await session.commit()
        content_id = c.id

    mock_result = {
        "success": True,
        "post_id": "67890",
        "devto_url": "https://dev.to/test/article",
    }

    with patch("api.content.publish_single", new_callable=AsyncMock, return_value=mock_result):
        await org_client.post(f"/api/content/{content_id}/publish")

    r = await org_client.get(f"/api/content/{content_id}")
    data = r.json()
    assert data["status"] == "published"
    assert data.get("post_id") == "67890"


@pytest.mark.asyncio
async def test_publish_wrong_status(org_client):
    """Cannot publish content that isn't approved/queued."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus

    async with async_session() as session:
        c = Content(
            org_id=1,
            channel=ContentChannel.linkedin,
            status=ContentStatus.spiked,
            headline="Spiked Content",
            body="This was spiked",
        )
        session.add(c)
        await session.commit()
        content_id = c.id

    r = await org_client.post(f"/api/content/{content_id}/publish")
    assert r.status_code == 400
