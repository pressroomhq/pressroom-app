"""T7 — Assets & Properties CRUD."""

import pytest


# ── Assets ──

@pytest.mark.asyncio
async def test_list_assets_empty(org_client):
    """T7.1 — Empty org returns empty list."""
    r = await org_client.get("/api/assets")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_asset(org_client):
    """T7.2 — Create asset."""
    r = await org_client.post(
        "/api/assets",
        json={
            "asset_type": "blog",
            "url": "https://blog.test.com",
            "label": "Company Blog",
            "description": "Main blog",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["url"] == "https://blog.test.com"


@pytest.mark.asyncio
async def test_list_after_create(org_client):
    """T7.3 — Asset appears in list after creation."""
    await org_client.post(
        "/api/assets",
        json={"asset_type": "repo", "url": "https://github.com/test/repo"},
    )
    r = await org_client.get("/api/assets")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_delete_asset(org_client):
    """T7.4 — Delete asset."""
    r = await org_client.post(
        "/api/assets",
        json={"asset_type": "docs", "url": "https://docs.test.com"},
    )
    asset_id = r.json()["id"]

    r2 = await org_client.delete(f"/api/assets/{asset_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == asset_id

    # Verify gone
    r3 = await org_client.get("/api/assets")
    assert not any(a["id"] == asset_id for a in r3.json())


@pytest.mark.asyncio
async def test_update_asset(org_client):
    """Update asset label."""
    r = await org_client.post(
        "/api/assets",
        json={"asset_type": "social", "url": "https://twitter.com/test"},
    )
    asset_id = r.json()["id"]

    r2 = await org_client.put(
        f"/api/assets/{asset_id}",
        json={"label": "Twitter Profile"},
    )
    assert r2.status_code == 200
    assert r2.json()["label"] == "Twitter Profile"


@pytest.mark.asyncio
async def test_filter_by_type(org_client):
    """Filter assets by type query param."""
    await org_client.post("/api/assets", json={"asset_type": "repo", "url": "https://gh.com/1"})
    await org_client.post("/api/assets", json={"asset_type": "blog", "url": "https://blog.com/1"})

    r = await org_client.get("/api/assets?type=repo")
    assert r.status_code == 200
    for a in r.json():
        assert a["asset_type"] == "repo"


# ── Properties ──

@pytest.mark.asyncio
async def test_list_properties_empty(org_client):
    """T7.5 — Empty org returns empty list."""
    r = await org_client.get("/api/properties")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_property(org_client):
    """T7.6 — Create property with repo_url."""
    r = await org_client.post(
        "/api/properties",
        json={
            "name": "Docs Site",
            "domain": "docs.test.com",
            "repo_url": "https://github.com/test/docs",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["domain"] == "docs.test.com"


@pytest.mark.asyncio
async def test_delete_property(org_client):
    """T7.7 — Delete property."""
    r = await org_client.post(
        "/api/properties",
        json={"name": "Temp Site", "domain": "temp.test.com"},
    )
    prop_id = r.json()["id"]

    r2 = await org_client.delete(f"/api/properties/{prop_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == prop_id


@pytest.mark.asyncio
async def test_update_property(org_client):
    """Update property name."""
    r = await org_client.post(
        "/api/properties",
        json={"name": "Original", "domain": "orig.com"},
    )
    prop_id = r.json()["id"]

    r2 = await org_client.put(
        f"/api/properties/{prop_id}",
        json={"name": "Updated Name"},
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "Updated Name"
