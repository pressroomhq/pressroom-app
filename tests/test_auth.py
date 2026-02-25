"""T1 — Auth & Access Control tests (Supabase Auth).

Tests the new Supabase Auth endpoints and auth-disabled dev mode.
Auth is disabled in tests (PRESSROOM_AUTH_DISABLED=1), so:
  - /api/auth/me requires a Supabase JWT (returns 401 without one)
  - /api/auth/request-access is public (no auth needed)
  - Org-scoped endpoints use X-Org-Id header (auth bypass)
  - Admin endpoints (/api/auth/admin/*) require a real Supabase admin JWT
"""

import pytest


# ── Public endpoints ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_access(client):
    """POST /api/auth/request-access creates a pending AccessRequest."""
    r = await client.post(
        "/api/auth/request-access",
        json={"email": "newuser@example.com", "name": "New User", "reason": "Testing"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_request_access_duplicate(client):
    """Duplicate request returns ok with 'already received' message."""
    body = {"email": "dup@example.com", "name": "Dup", "reason": "Test"}
    await client.post("/api/auth/request-access", json=body)
    r = await client.post("/api/auth/request-access", json=body)
    assert r.status_code == 200
    assert "already received" in r.json()["message"]


@pytest.mark.asyncio
async def test_request_access_missing_email(client):
    """Request access without email returns 422."""
    r = await client.post(
        "/api/auth/request-access",
        json={"name": "No Email"},
    )
    assert r.status_code == 422


# ── /api/auth/me — Supabase JWT required ────────────────────────────────────

@pytest.mark.asyncio
async def test_me_no_token(client):
    """GET /me without token returns 401."""
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client):
    """GET /me with invalid token returns 401."""
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid_token_xxx"},
    )
    assert r.status_code == 401


# ── Admin endpoints require Supabase JWT ─────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_users_requires_auth(client):
    """POST /api/auth/admin/users rejects unauthenticated requests."""
    r = await client.post(
        "/api/auth/admin/users",
        json={"email": "someone@example.com", "name": "Someone"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_users_requires_auth(client):
    """GET /api/auth/admin/users rejects unauthenticated requests."""
    r = await client.get("/api/auth/admin/users")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_requests_requires_auth(client):
    """GET /api/auth/admin/requests rejects unauthenticated requests."""
    r = await client.get("/api/auth/admin/requests")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_keys_requires_auth(client):
    """GET /api/auth/api-keys rejects unauthenticated requests."""
    r = await client.get("/api/auth/api-keys")
    assert r.status_code == 401


# ── Health + auth-disabled mode ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_reports_auth_disabled(client):
    """Health endpoint reports auth_disabled=True in test mode."""
    r = await client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "on the wire"
    assert data["auth_disabled"] is True


# ── Org isolation (uses org_client with auth disabled) ───────────────────────

@pytest.mark.asyncio
async def test_org_isolation(org_client, test_org_id, second_org):
    """Org A cannot read Org B data."""
    from database import async_session
    from models import Signal, SignalType

    # Create signal in test org
    async with async_session() as session:
        sig = Signal(
            org_id=test_org_id,
            type=SignalType.hackernews,
            source="HN",
            title="Org 1 Signal",
        )
        session.add(sig)
        await session.commit()

    # Test org can see it
    r1 = await org_client.get("/api/signals")
    assert r1.status_code == 200
    assert any(s["title"] == "Org 1 Signal" for s in r1.json())

    # Second org cannot see it
    org_client.headers["X-Org-Id"] = str(second_org)
    r2 = await org_client.get("/api/signals")
    assert r2.status_code == 200
    assert not any(s["title"] == "Org 1 Signal" for s in r2.json())

    # Restore original org header
    org_client.headers["X-Org-Id"] = str(test_org_id)
