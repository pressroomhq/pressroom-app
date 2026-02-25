"""T1 — Auth & Session tests.

Migration sensitivity: High. Entire auth model changes in Phase 4.
These tests establish the baseline for login/logout/session behavior.
"""

import pytest


@pytest.mark.asyncio
async def test_login_valid(client):
    """T1.1 — Valid credentials return 200 with token."""
    r = await client.post(
        "/api/auth/login",
        json={"email": "test@test.com", "password": "testpassword123"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["token"].startswith("ps_")
    assert "user" in data
    assert data["user"]["email"] == "test@test.com"
    assert "orgs" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    """T1.2 — Wrong password returns 401."""
    r = await client.post(
        "/api/auth/login",
        json={"email": "test@test.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    """T1.3 — Unknown email returns 401."""
    r = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_valid_token(authed_client):
    """T1.4 — GET /me with valid token returns user."""
    r = await authed_client.get("/api/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["email"] == "test@test.com"
    assert "orgs" in data


@pytest.mark.asyncio
async def test_me_no_token(client):
    """T1.5 — GET /me without token returns 401."""
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(client):
    """T1.6 — GET /me with invalid token returns 401."""
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid_token_xxx"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout(authed_client):
    """T1.7 — Logout invalidates the session token."""
    # Logout
    r = await authed_client.post("/api/auth/logout")
    assert r.status_code == 200

    # Token should now be invalid
    r2 = await authed_client.get("/api/auth/me")
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_org_isolation(org_client, second_org):
    """T1.8 — Org A cannot read Org B data."""
    from database import async_session
    from models import Signal, SignalType

    # Create signal in org 1
    async with async_session() as session:
        sig = Signal(
            org_id=1,
            type=SignalType.hackernews,
            source="HN",
            title="Org 1 Signal",
        )
        session.add(sig)
        await session.commit()

    # Org 1 can see it
    r1 = await org_client.get("/api/signals")
    assert r1.status_code == 200
    assert any(s["title"] == "Org 1 Signal" for s in r1.json())

    # Org 2 cannot see it
    org_client.headers["X-Org-Id"] = str(second_org)
    r2 = await org_client.get("/api/signals")
    assert r2.status_code == 200
    assert not any(s["title"] == "Org 1 Signal" for s in r2.json())


@pytest.mark.asyncio
async def test_request_access(client):
    """Request access creates a pending AccessRequest."""
    r = await client.post(
        "/api/auth/request-access",
        json={"email": "newuser@example.com", "name": "New User", "reason": "Testing"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_request_access_duplicate(client):
    """Duplicate request returns ok without creating another."""
    body = {"email": "dup@example.com", "name": "Dup", "reason": "Test"}
    await client.post("/api/auth/request-access", json=body)
    r = await client.post("/api/auth/request-access", json=body)
    assert r.status_code == 200
    assert "already received" in r.json()["message"]


@pytest.mark.asyncio
async def test_invite_flow(client):
    """Admin creates user → invite token → set password → login."""
    # Create user
    r = await client.post(
        "/api/auth/admin/users",
        json={"email": "invited@test.com", "name": "Invited", "org_ids": [1]},
    )
    assert r.status_code == 200
    token = r.json()["invite_token"]
    assert token.startswith("inv_")

    # Check invite is valid
    r2 = await client.get(f"/api/auth/invite/{token}")
    assert r2.status_code == 200
    assert r2.json()["valid"] is True
    assert r2.json()["email"] == "invited@test.com"

    # Set password
    r3 = await client.post(
        "/api/auth/set-password",
        json={"token": token, "password": "newpassword123"},
    )
    assert r3.status_code == 200

    # Login with new password
    r4 = await client.post(
        "/api/auth/login",
        json={"email": "invited@test.com", "password": "newpassword123"},
    )
    assert r4.status_code == 200
    assert "token" in r4.json()
