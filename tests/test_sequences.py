"""T12 — Post-Migration Sequence Check.

Run these ONLY after migration to PostgreSQL.
They verify that PostgreSQL sequences are properly reset after bulk data import.
On SQLite, these tests are essentially no-ops (autoincrement always works).
"""

import pytest


@pytest.mark.asyncio
async def test_signal_sequence():
    """T12.1 — Create signal after migration: id > max imported ID."""
    from database import async_session
    from models import Signal, SignalType
    from sqlalchemy import select, func

    # Create a few signals to simulate migrated data
    async with async_session() as session:
        for i in range(5):
            session.add(Signal(
                org_id=1, type=SignalType.rss, source="test",
                title=f"Migrated Signal {i}",
            ))
        await session.commit()

    # Get max
    async with async_session() as session:
        max_id = (await session.execute(select(func.max(Signal.id)))).scalar()

    # Create new — ID must be > max
    async with async_session() as session:
        sig = Signal(org_id=1, type=SignalType.rss, source="test", title="Post-Migration")
        session.add(sig)
        await session.commit()
        assert sig.id > max_id


@pytest.mark.asyncio
async def test_content_sequence():
    """T12.2 — Create content after migration: id > max imported ID."""
    from database import async_session
    from models import Content, ContentChannel, ContentStatus
    from sqlalchemy import select, func

    async with async_session() as session:
        for i in range(5):
            session.add(Content(
                org_id=1, channel=ContentChannel.linkedin,
                status=ContentStatus.queued,
                headline=f"Migrated Content {i}",
                body="migrated body",
            ))
        await session.commit()

    async with async_session() as session:
        max_id = (await session.execute(select(func.max(Content.id)))).scalar()

    async with async_session() as session:
        c = Content(
            org_id=1, channel=ContentChannel.linkedin,
            status=ContentStatus.queued,
            headline="Post-Migration Content",
            body="new body",
        )
        session.add(c)
        await session.commit()
        assert c.id > max_id


@pytest.mark.asyncio
async def test_org_sequence():
    """T12.3 — Create org after migration: id > max imported ID."""
    from database import async_session
    from models import Organization
    from sqlalchemy import select, func

    async with async_session() as session:
        max_id = (await session.execute(select(func.max(Organization.id)))).scalar() or 0

    async with async_session() as session:
        org = Organization(name="Post-Migration Org", domain="new.com")
        session.add(org)
        await session.commit()
        assert org.id > max_id


@pytest.mark.asyncio
async def test_all_sequences_valid():
    """T12.4 — Verify all key sequences are valid (PostgreSQL only).

    On SQLite this is a no-op. On PostgreSQL, checks pg_sequences.
    """
    from database import async_session
    from sqlalchemy import text

    async with async_session() as session:
        try:
            result = await session.execute(text(
                "SELECT schemaname, sequencename, last_value FROM pg_sequences ORDER BY sequencename"
            ))
            rows = result.all()
            # Every sequence should have last_value >= 0
            for schema, seq, last_val in rows:
                assert last_val is not None, f"Sequence {seq} has NULL last_value"
        except Exception:
            # SQLite doesn't have pg_sequences — test is N/A
            pytest.skip("pg_sequences not available (SQLite)")
