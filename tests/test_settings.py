"""T2 — Org & Settings tests."""

import pytest


@pytest.mark.asyncio
async def test_get_settings(org_client):
    """T2.1 — GET /api/settings returns dict."""
    r = await org_client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_save_setting(org_client):
    """T2.2 — Save golden_anchor setting."""
    r = await org_client.put(
        "/api/settings",
        json={"settings": {"golden_anchor": "We help developers build faster APIs."}},
    )
    assert r.status_code == 200
    data = r.json()
    assert "golden_anchor" in data.get("updated", [])


@pytest.mark.asyncio
async def test_get_saved_setting(org_client):
    """T2.3 — After save, setting is returned."""
    # Save
    await org_client.put(
        "/api/settings",
        json={"settings": {"golden_anchor": "Test anchor value"}},
    )

    # Read back
    r = await org_client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    anchor = data.get("golden_anchor", {})
    assert anchor.get("is_set") is True


@pytest.mark.asyncio
async def test_list_orgs(org_client):
    """T2.4 — GET /api/orgs returns list."""
    r = await org_client.get("/api/orgs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_create_org(org_client):
    """T2.5 — POST /api/orgs creates new org."""
    r = await org_client.post(
        "/api/orgs",
        json={"name": "New Test Org", "domain": "neworg.com"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["name"] == "New Test Org"


@pytest.mark.asyncio
async def test_get_org(org_client, test_org_id):
    """GET /api/orgs/{id} returns org details."""
    r = await org_client.get(f"/api/orgs/{test_org_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "DreamFactory Test"


@pytest.mark.asyncio
async def test_settings_status(org_client):
    """GET /api/settings/status returns connection statuses."""
    r = await org_client.get("/api/settings/status")
    assert r.status_code == 200
    data = r.json()
    assert "anthropic" in data
    assert "github" in data
