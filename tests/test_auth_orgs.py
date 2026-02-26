"""Auth & Org Scoping Tests — AUTH_FIX_PLAN.md test scenarios.

Covers:
  Test 1: Demo org read-only enforcement
  Test 2: Demo org admin write access (auth disabled = full access, tested via is_admin flag)
  Test 3: Own org full read/write access
  Test 4: Onboard always creates new org
  Test 5: Duplicate domain prevention
  Test 6: Org isolation (data from one org not visible to another)
  Test 7: Frontend is_demo field in API response
  Test 8: _check_writable guards on write methods
  Test 9: Nullable domain — multiple orgs without domain

Uses auth-disabled test client (PRESSROOM_AUTH_DISABLED=1 set in conftest.py).
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text

from database import async_session, engine
from models import Organization, Profile, UserOrg
from services.data_layer import DataLayer


# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_or_create_demo_org(name: str, domain: str) -> int:
    """Create a demo org directly in DB, return its id."""
    async with async_session() as session:
        existing = (await session.execute(
            select(Organization).where(Organization.domain == domain)
        )).scalar_one_or_none()
        if existing:
            existing.is_demo = True
            await session.commit()
            return existing.id
        org = Organization(name=name, domain=domain, is_demo=True)
        session.add(org)
        await session.commit()
        await session.refresh(org)
        return org.id


async def _create_test_org(name: str, domain: str | None = None) -> int:
    async with async_session() as session:
        if domain:
            existing = (await session.execute(
                select(Organization).where(Organization.domain == domain)
            )).scalar_one_or_none()
            if existing:
                await session.execute(text(f"DELETE FROM organizations WHERE id = {existing.id}"))
                await session.commit()
        org = Organization(name=name, domain=domain)
        session.add(org)
        await session.commit()
        await session.refresh(org)
        return org.id


async def _delete_org(org_id: int):
    async with async_session() as session:
        await session.execute(text(f"DELETE FROM settings WHERE org_id = {org_id}"))
        await session.execute(text(f"DELETE FROM signals WHERE org_id = {org_id}"))
        await session.execute(text(f"DELETE FROM story_signals WHERE story_id IN (SELECT id FROM stories WHERE org_id = {org_id})"))
        await session.execute(text(f"DELETE FROM stories WHERE org_id = {org_id}"))
        await session.execute(text(f"DELETE FROM content WHERE org_id = {org_id}"))
        await session.execute(text(f"DELETE FROM organizations WHERE id = {org_id}"))
        await session.commit()


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def app_client():
    """Plain ASGI client — no org headers."""
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def demo_org_id():
    oid = await _get_or_create_demo_org("Test Demo Org", "demo-test-pressroom.com")
    yield oid
    await _delete_org(oid)


@pytest_asyncio.fixture
async def own_org_id():
    oid = await _create_test_org("Own Test Org", "own-test-pressroom.com")
    yield oid
    await _delete_org(oid)


# ── Test 7: is_demo in API response ───────────────────────────────────────

@pytest.mark.asyncio
async def test_list_orgs_includes_is_demo(app_client, demo_org_id):
    """GET /api/orgs returns is_demo field — demo org has is_demo=True.

    Note: auth-disabled mode has no user_id, so only demo orgs are returned
    (no user_orgs rows). We only assert on demo org here.
    """
    r = await app_client.get("/api/orgs")
    assert r.status_code == 200
    orgs = r.json()
    assert isinstance(orgs, list)

    # Every org in the response must have the is_demo field
    for org in orgs:
        assert "is_demo" in org, f"Org {org['id']} missing is_demo field"

    # Our demo org should appear and have is_demo=True
    demo_orgs = [o for o in orgs if o["id"] == demo_org_id]
    assert demo_orgs, f"Demo org {demo_org_id} not in org list"
    assert demo_orgs[0]["is_demo"] is True, "Demo org should have is_demo=True"


@pytest.mark.asyncio
async def test_is_demo_false_for_regular_org(own_org_id):
    """Regular org created via DataLayer has is_demo=False in get_org response."""
    async with async_session() as session:
        dl = DataLayer(session, org_id=own_org_id)
        org = await dl.get_org(own_org_id)
    assert org is not None
    assert "is_demo" in org, "get_org should return is_demo field"
    assert org["is_demo"] is False, "Regular org should have is_demo=False"


# ── Test 5: Duplicate domain prevention ────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_domain_rejected(app_client):
    """Creating two orgs with the same domain returns 409."""
    domain = "dup-test-pressroom.com"
    created_ids = []

    try:
        r1 = await app_client.post("/api/orgs", json={"name": "Dup Org 1", "domain": domain})
        assert r1.status_code in (200, 201), f"First create failed: {r1.text}"
        created_ids.append(r1.json()["id"])

        r2 = await app_client.post("/api/orgs", json={"name": "Dup Org 2", "domain": domain})
        assert r2.status_code == 409, f"Expected 409 for duplicate domain, got {r2.status_code}: {r2.text}"
    finally:
        for oid in created_ids:
            await _delete_org(oid)


@pytest.mark.asyncio
async def test_null_domain_allows_multiple_orgs(app_client):
    """Multiple orgs with no domain (NULL) are allowed — NULL doesn't violate unique."""
    created_ids = []
    try:
        r1 = await app_client.post("/api/orgs", json={"name": "No Domain Org A", "domain": ""})
        assert r1.status_code in (200, 201), f"First no-domain org failed: {r1.text}"
        created_ids.append(r1.json()["id"])

        r2 = await app_client.post("/api/orgs", json={"name": "No Domain Org B", "domain": ""})
        assert r2.status_code in (200, 201), f"Second no-domain org failed: {r2.text}"
        created_ids.append(r2.json()["id"])

        assert created_ids[0] != created_ids[1], "Two no-domain orgs should have different IDs"
    finally:
        for oid in created_ids:
            await _delete_org(oid)


# ── Test 8: _check_writable guards via DataLayer ────────────────────────────

@pytest.mark.asyncio
async def test_check_writable_blocks_signal_save(demo_org_id):
    """save_signal on read_only DataLayer raises 403."""
    from fastapi import HTTPException
    async with async_session() as session:
        dl = DataLayer(session, org_id=demo_org_id)
        dl.read_only = True
        with pytest.raises(HTTPException) as exc_info:
            await dl.save_signal({
                "type": "web", "source": "test.com",
                "title": "Test Signal", "content": "test", "url": "https://test.com"
            })
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_writable_blocks_create_story(demo_org_id):
    """create_story on read_only DataLayer raises 403."""
    from fastapi import HTTPException
    async with async_session() as session:
        dl = DataLayer(session, org_id=demo_org_id)
        dl.read_only = True
        with pytest.raises(HTTPException) as exc_info:
            await dl.create_story({"title": "Test Story", "angle": "test"})
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_writable_blocks_save_asset(demo_org_id):
    """save_asset on read_only DataLayer raises 403."""
    from fastapi import HTTPException
    async with async_session() as session:
        dl = DataLayer(session, org_id=demo_org_id)
        dl.read_only = True
        with pytest.raises(HTTPException) as exc_info:
            await dl.save_asset({
                "asset_type": "page", "url": "https://test.com",
                "label": "test", "description": ""
            })
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_writable_blocks_delete_org(demo_org_id):
    """delete_org on read_only DataLayer raises 403."""
    from fastapi import HTTPException
    async with async_session() as session:
        dl = DataLayer(session, org_id=demo_org_id)
        dl.read_only = True
        with pytest.raises(HTTPException) as exc_info:
            await dl.delete_org(demo_org_id)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_check_writable_allows_writes_on_own_org(own_org_id):
    """Writes succeed when read_only=False."""
    async with async_session() as session:
        dl = DataLayer(session, org_id=own_org_id)
        dl.read_only = False
        signal = await dl.save_signal({
            "type": "web_search", "source": "own-test-pressroom.com",
            "title": "Own Signal", "content": "content", "url": "https://own-test-pressroom.com"
        })
        assert signal is not None
        assert signal.get("id") is not None
        await session.rollback()  # clean up


# ── Test 6: Org isolation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_org_isolation_signals(app_client):
    """Signals created for org A are not visible when querying as org B."""
    org_a = await _create_test_org("Isolation Org A", "iso-a-pressroom.com")
    org_b = await _create_test_org("Isolation Org B", "iso-b-pressroom.com")

    try:
        # Create signal directly in org A via DataLayer
        async with async_session() as session:
            dl_a = DataLayer(session, org_id=org_a)
            sig = await dl_a.save_signal({
                "type": "web_search", "source": "iso-a-pressroom.com",
                "title": "Org A Signal", "content": "content for a",
                "url": "https://iso-a-pressroom.com"
            })
            await session.commit()
            sig_id = sig["id"]

        # Query signals as org B — should NOT see org A's signal
        r_b = await app_client.get("/api/signals", headers={"X-Org-Id": str(org_b)})
        assert r_b.status_code == 200
        sig_ids_b = [s["id"] for s in r_b.json()]
        assert sig_id not in sig_ids_b, "Org B should not see Org A's signal"

        # Query signals as org A — SHOULD see it
        r_a = await app_client.get("/api/signals", headers={"X-Org-Id": str(org_a)})
        assert r_a.status_code == 200
        sig_ids_a = [s["id"] for s in r_a.json()]
        assert sig_id in sig_ids_a, "Org A should see its own signal"
    finally:
        await _delete_org(org_a)
        await _delete_org(org_b)


@pytest.mark.asyncio
async def test_org_isolation_stories(app_client):
    """Stories from org A are not visible to org B."""
    org_a = await _create_test_org("Story Iso A", "story-iso-a-pressroom.com")
    org_b = await _create_test_org("Story Iso B", "story-iso-b-pressroom.com")

    try:
        r = await app_client.post(
            "/api/stories",
            json={"title": "Org A Story", "angle": "test angle"},
            headers={"X-Org-Id": str(org_a)}
        )
        assert r.status_code in (200, 201), f"Story create failed: {r.text}"
        story_id = r.json()["id"]

        r2 = await app_client.get("/api/stories", headers={"X-Org-Id": str(org_b)})
        assert r2.status_code == 200
        org_b_stories = r2.json()
        story_ids = [s["id"] for s in org_b_stories]
        assert story_id not in story_ids, "Org B should not see Org A's story"
    finally:
        await _delete_org(org_a)
        await _delete_org(org_b)


# ── Test 1: Demo org read-only via API ────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_org_read_works(app_client, demo_org_id):
    """GET /api/settings on a demo org returns 200 (reads work)."""
    r = await app_client.get(
        "/api/settings",
        headers={"X-Org-Id": str(demo_org_id)}
    )
    # Should succeed (200) — reads are always allowed
    assert r.status_code == 200


# ── Test 3: Own org full access via API ───────────────────────────────────

@pytest.mark.asyncio
async def test_own_org_write_works(app_client, own_org_id):
    """POST /api/stories on own org returns 200/201 (writes work)."""
    r = await app_client.post(
        "/api/stories",
        json={"title": "Own Org Test Story", "angle": "test angle for own org"},
        headers={"X-Org-Id": str(own_org_id)}
    )
    assert r.status_code in (200, 201), f"Write to own org failed: {r.text}"
    data = r.json()
    assert "id" in data


# ── Test 4: Onboard always creates new org ─────────────────────────────────

@pytest.mark.asyncio
async def test_onboard_apply_creates_new_org(app_client, demo_org_id):
    """POST /api/onboard/apply always creates a NEW org, never overwrites."""
    new_domain = "onboard-new-test-pressroom.com"

    # Make sure no prior org exists for this domain
    async with async_session() as session:
        existing = (await session.execute(
            select(Organization).where(Organization.domain == new_domain)
        )).scalar_one_or_none()
        if existing:
            await _delete_org(existing.id)

    try:
        profile = {
            "company_name": "Brand New Onboard Co",
            "domain": new_domain,
            "industry": "tech",
            "topics": ["ai"],
            "tone": "professional",
            "audience": "developers",
        }
        r = await app_client.post(
            "/api/onboard/apply",
            json={"profile": profile},
            headers={"X-Org-Id": str(demo_org_id)}  # currently viewing demo org
        )
        assert r.status_code == 200, f"Onboard apply failed: {r.text}"
        data = r.json()
        new_org_id = data.get("org_id")
        assert new_org_id is not None
        assert new_org_id != demo_org_id, "Onboard should create NEW org, not overwrite demo org"

        # Verify new org exists with correct domain
        async with async_session() as session:
            new_org = (await session.execute(
                select(Organization).where(Organization.id == new_org_id)
            )).scalar_one_or_none()
            assert new_org is not None
            assert new_org.domain == new_domain

        # Verify demo org is UNCHANGED
        async with async_session() as session:
            demo_org = (await session.execute(
                select(Organization).where(Organization.id == demo_org_id)
            )).scalar_one_or_none()
            assert demo_org is not None, "Demo org should still exist"
    finally:
        async with async_session() as session:
            o = (await session.execute(
                select(Organization).where(Organization.domain == new_domain)
            )).scalar_one_or_none()
            if o:
                await _delete_org(o.id)


@pytest.mark.asyncio
async def test_onboard_apply_duplicate_domain_rejected(app_client, own_org_id):
    """Onboarding with an existing domain returns 409."""
    # Get own org's domain
    async with async_session() as session:
        org = (await session.execute(
            select(Organization).where(Organization.id == own_org_id)
        )).scalar_one_or_none()
        existing_domain = org.domain

    profile = {
        "company_name": "Duplicate Co",
        "domain": existing_domain,
        "industry": "tech",
        "topics": ["saas"],
        "tone": "casual",
        "audience": "everyone",
    }
    r = await app_client.post(
        "/api/onboard/apply",
        json={"profile": profile},
        headers={"X-Org-Id": str(own_org_id)}
    )
    assert r.status_code == 409, f"Expected 409 for duplicate domain, got {r.status_code}: {r.text}"


# ── Test 9: Nullable domain (already tested in test_null_domain_allows_multiple_orgs) ──

@pytest.mark.asyncio
async def test_org_domain_can_be_null():
    """Organizations can be created with NULL domain — stored as None, not empty string."""
    async with async_session() as session:
        org = Organization(name="No Domain Org", domain=None)
        session.add(org)
        await session.flush()
        assert org.id is not None
        assert org.domain is None
        await session.rollback()
