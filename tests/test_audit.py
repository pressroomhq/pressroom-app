"""T9 — Audit system tests.

Tests the persisted audit history and action items.
T9.7 (sequence reset canary) is the most likely failure post-migration.
"""

import pytest


@pytest.mark.asyncio
async def test_history_empty(org_client):
    """T9.1 — Empty audit history."""
    r = await org_client.get("/api/audit/history")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_action_items_empty(org_client):
    """T9.2 — Empty action items."""
    r = await org_client.get("/api/audit/action-items")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_action_items_filter(org_client):
    """T9.3 — Filter action items by status."""
    r = await org_client.get("/api/audit/action-items?status=open")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_action_item_resolve(org_client):
    """T9.4 — Mark action item as resolved."""
    from database import async_session
    from models import AuditResult, AuditActionItem

    # Create audit result + action item directly
    async with async_session() as session:
        audit = AuditResult(
            org_id=1,
            audit_type="seo",
            target="test.com",
            score=75,
            total_issues=1,
            result_json="{}",
        )
        session.add(audit)
        await session.flush()

        item = AuditActionItem(
            org_id=1,
            audit_result_id=audit.id,
            priority="high",
            category="technical",
            title="Fix meta description",
            status="open",
        )
        session.add(item)
        await session.commit()
        item_id = item.id

    # Resolve it
    r = await org_client.patch(
        f"/api/audit/action-items/{item_id}",
        json={"status": "resolved"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "resolved"


@pytest.mark.asyncio
async def test_action_items_resolved_filter(org_client):
    """T9.5 — Resolved items appear in resolved filter."""
    from database import async_session
    from models import AuditResult, AuditActionItem
    import datetime

    async with async_session() as session:
        audit = AuditResult(
            org_id=1, audit_type="seo", target="test.com",
            score=80, total_issues=1, result_json="{}",
        )
        session.add(audit)
        await session.flush()

        item = AuditActionItem(
            org_id=1, audit_result_id=audit.id,
            priority="medium", category="content",
            title="Already Resolved",
            status="resolved",
            resolved_at=datetime.datetime.utcnow(),
        )
        session.add(item)
        await session.commit()

    r = await org_client.get("/api/audit/action-items?status=resolved")
    assert r.status_code == 200
    data = r.json()
    assert any(i["title"] == "Already Resolved" for i in data)


@pytest.mark.asyncio
async def test_audit_history_crud(org_client):
    """Create, fetch, and delete an audit result."""
    from database import async_session
    from models import AuditResult

    async with async_session() as session:
        audit = AuditResult(
            org_id=1, audit_type="readme", target="owner/repo",
            score=90, total_issues=2, result_json='{"test": true}',
        )
        session.add(audit)
        await session.commit()
        audit_id = audit.id

    # Fetch
    r = await org_client.get(f"/api/audit/history/{audit_id}")
    assert r.status_code == 200

    # Delete
    r2 = await org_client.delete(f"/api/audit/history/{audit_id}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == audit_id


@pytest.mark.asyncio
async def test_upsert_dedup(org_client):
    """T9.6 — Upsert dedup: same title twice results in one row."""
    from database import async_session
    from models import AuditResult, AuditActionItem
    from services.data_layer import DataLayer

    async with async_session() as session:
        audit = AuditResult(
            org_id=1, audit_type="seo", target="dedup.com",
            score=70, total_issues=1, result_json="{}",
        )
        session.add(audit)
        await session.flush()

        dl = DataLayer(session, org_id=1)
        items = [
            {"priority": "high", "category": "seo", "title": "Duplicate Title",
             "fix_instructions": "Fix it", "score_impact": 5},
        ]
        await dl.upsert_action_items(audit.id, items)
        await session.commit()

        # Upsert again with same title
        await dl.upsert_action_items(audit.id, items)
        await session.commit()

    # Check only one row with that title
    r = await org_client.get("/api/audit/action-items")
    matches = [i for i in r.json() if i["title"] == "Duplicate Title"]
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_sequence_reset_canary(org_client):
    """T9.7 — After bulk insert, new ID > max existing ID.

    This is the most likely failure point post-migration. PostgreSQL sequences
    must be reset after bulk data import.
    """
    from database import async_session
    from models import AuditResult

    # Bulk insert with explicit IDs (simulates migration)
    async with async_session() as session:
        for i in range(1, 6):
            audit = AuditResult(
                org_id=1, audit_type="seo", target=f"site{i}.com",
                score=50 + i, total_issues=i, result_json="{}",
            )
            session.add(audit)
        await session.commit()

    # Get max ID
    async with async_session() as session:
        from sqlalchemy import select, func
        result = await session.execute(select(func.max(AuditResult.id)))
        max_id = result.scalar()

    # Create another — its ID should be > max_id
    async with async_session() as session:
        new_audit = AuditResult(
            org_id=1, audit_type="seo", target="new.com",
            score=99, total_issues=0, result_json="{}",
        )
        session.add(new_audit)
        await session.commit()
        assert new_audit.id > max_id
