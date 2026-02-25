"""Test fixtures — PostgreSQL + Supabase Auth.

Uses the real Supabase PostgreSQL DB with auth disabled for testing.
Tests use org_client (X-Org-Id header only) since auth is bypassed.
"""

import os
import asyncio

# Auth disabled for tests — endpoints skip JWT validation
os.environ["PRESSROOM_AUTH_DISABLED"] = "1"

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from database import engine, Base, async_session
from main import app
from models import Organization

TEST_ORG_NAME = "DreamFactory Test"
TEST_ORG_DOMAIN = "dreamfactory-test.com"


# ── Session-scoped event loop so asyncpg connections stay valid across tests ──

@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for all tests — required for asyncpg connection reuse."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Module-level state holder ─────────────────────────────────────────────────

_test_state = {}


async def _cleanup_org_data(org_id: int):
    """Delete all test data for an org, respecting FK constraints.

    Uses savepoints so a single failed DELETE doesn't abort the whole
    transaction (PostgreSQL requires this, unlike SQLite).
    """
    from sqlalchemy import text

    # FK child tables first (no org_id column — join through parent)
    fk_deletes = [
        "DELETE FROM story_signals WHERE story_id IN (SELECT id FROM stories WHERE org_id = :oid)",
        "DELETE FROM content_performance WHERE content_id IN (SELECT id FROM content WHERE org_id = :oid)",
        "DELETE FROM email_drafts WHERE content_id IN (SELECT id FROM content WHERE org_id = :oid)",
        "DELETE FROM youtube_scripts WHERE content_id IN (SELECT id FROM content WHERE org_id = :oid)",
    ]
    # Tables with org_id column (order matters for remaining FKs)
    org_tables = [
        'content', 'stories', 'signals', 'briefs', 'settings',
        'company_assets', 'blog_posts',
        'wire_signals', 'wire_sources', 'org_sources', 'site_properties',
    ]

    async with async_session() as session:
        for stmt in fk_deletes:
            try:
                async with session.begin_nested():
                    await session.execute(text(stmt), {"oid": org_id})
            except Exception:
                pass

        for table in org_tables:
            try:
                async with session.begin_nested():
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE org_id = :oid"),
                        {"oid": org_id},
                    )
            except Exception:
                pass

        await session.commit()


@pytest_asyncio.fixture(autouse=True, scope="session")
async def seed_org():
    """One-time: seed a test org (tables already exist in the live PostgreSQL DB)."""
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.execute(
            select(Organization).where(Organization.domain == TEST_ORG_DOMAIN)
        )
        org = existing.scalar_one_or_none()
        if not org:
            org = Organization(name=TEST_ORG_NAME, domain=TEST_ORG_DOMAIN)
            session.add(org)
            await session.commit()
            await session.refresh(org)

        _test_state["org_id"] = org.id

    # Pre-cleanup: remove leftover test data from previous runs
    await _cleanup_org_data(_test_state["org_id"])

    yield

    # Post-cleanup
    await _cleanup_org_data(_test_state["org_id"])

    # Also clean up second_org if created
    second_id = _test_state.get("second_org_id")
    if second_id:
        await _cleanup_org_data(second_id)

    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_per_test(seed_org):
    """Per-test cleanup: remove content created during previous tests."""
    org_id = _test_state["org_id"]
    await _cleanup_org_data(org_id)
    yield


@pytest_asyncio.fixture
def test_org_id(seed_org):
    """The ID of the test org."""
    return _test_state["org_id"]


@pytest_asyncio.fixture
async def client():
    """Unauthenticated async HTTP client against the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def org_client(client, test_org_id):
    """Client with X-Org-Id header (auth disabled, for most endpoints)."""
    client.headers.update({
        "X-Org-Id": str(test_org_id),
        "Content-Type": "application/json",
    })
    return client


@pytest_asyncio.fixture
async def authed_client(org_client):
    """Alias for org_client — auth is disabled in tests."""
    return org_client


@pytest_asyncio.fixture
async def second_org():
    """Create a second org for isolation tests. Returns org_id."""
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.execute(
            select(Organization).where(Organization.domain == "other-test.com")
        )
        org = existing.scalar_one_or_none()
        if not org:
            org = Organization(name="Other Org", domain="other-test.com")
            session.add(org)
            await session.commit()
            await session.refresh(org)
        _test_state["second_org_id"] = org.id
        return org.id
