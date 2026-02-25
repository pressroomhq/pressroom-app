"""Test fixtures — isolated test DB, async client, auth helpers.

Uses a separate SQLite DB (test_pressroom.db) so production data is untouched.
After migration to PostgreSQL, just change DATABASE_URL and re-run.
"""

import os
import asyncio

# Force test DB before any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_pressroom.db"
os.environ["PRESSROOM_AUTH_DISABLED"] = "1"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from database import engine, Base, async_session
from main import app
from models import Organization, User, UserOrg, UserSession, Signal, SignalType
from api.user_auth import _hash_password

TEST_ORG_ID = 1
TEST_HEADERS = {"X-Org-Id": str(TEST_ORG_ID), "Content-Type": "application/json"}


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed test org + admin user
    async with async_session() as session:
        from sqlalchemy import select
        existing_org = await session.execute(select(Organization).where(Organization.id == TEST_ORG_ID))
        if not existing_org.scalar_one_or_none():
            org = Organization(name="Test Org", domain="test.com")
            session.add(org)
            await session.flush()

            admin = User(
                email="test@test.com",
                name="Test Admin",
                password_hash=_hash_password("testpassword123"),
                is_admin=1,
                is_active=1,
            )
            session.add(admin)
            await session.flush()

            session.add(UserOrg(user_id=admin.id, org_id=org.id))
            await session.commit()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Unauthenticated async HTTP client against the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def authed_client(client):
    """Client with a valid session token + org headers."""
    r = await client.post(
        "/api/auth/login",
        json={"email": "test@test.com", "password": "testpassword123"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    client.headers.update({
        "Authorization": f"Bearer {data['token']}",
        "X-Org-Id": str(TEST_ORG_ID),
        "Content-Type": "application/json",
    })
    return client


@pytest_asyncio.fixture
async def org_client(client):
    """Client with only X-Org-Id header (no auth, for endpoints that use get_data_layer)."""
    client.headers.update(TEST_HEADERS)
    return client


@pytest_asyncio.fixture
async def second_org():
    """Create a second org for isolation tests. Returns org_id."""
    async with async_session() as session:
        org = Organization(name="Other Org", domain="other.com")
        session.add(org)
        await session.commit()
        return org.id
