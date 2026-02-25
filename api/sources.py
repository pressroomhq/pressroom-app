"""Sources API — global source library and SIGINT feed.

Sources are shared across all orgs. Orgs subscribe to sources.
The sweep crawls all active sources into raw_signals.
Per-org feeds are scored via embedding similarity.

Vocabulary:
  Source     — a crawlable feed (subreddit, HN keyword, RSS, X search)
  OrgSource  — an org's subscription to a source
  RawSignal  — a crawled item, not yet org-filtered
  Sweep      — the global crawl run
  Feed       — an org's relevance-scored view of recent raw_signals
  Fingerprint — an org's embedded context vector
"""

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/sources", tags=["sources"])


# ── Request models ────────────────────────────────────────────────────────────

class SourceCreate(BaseModel):
    type: str                       # reddit | hackernews | rss | x_search | trends
    name: str                       # human label
    config: dict = {}               # type-specific config
    category_tags: list[str] = []
    fetch_interval_hours: int = 24


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    category_tags: Optional[list[str]] = None
    active: Optional[int] = None
    fetch_interval_hours: Optional[int] = None


class OrgSourceToggle(BaseModel):
    source_id: int
    enabled: bool = True


class SweepRequest(BaseModel):
    source_ids: Optional[list[int]] = None   # None = sweep all active sources


# ── Source library (admin / global) ──────────────────────────────────────────

@router.get("")
async def list_sources(
    type: Optional[str] = Query(None),
    active_only: bool = Query(True),
):
    """List all sources in the global library."""
    from database import async_session
    from models import Source
    from sqlalchemy import select

    async with async_session() as session:
        query = select(Source).order_by(Source.type, Source.name)
        if active_only:
            query = query.where(Source.active == True)
        if type:
            query = query.where(Source.type == type)
        result = await session.execute(query)
        sources = result.scalars().all()
        return [_serialize_source(s) for s in sources]


@router.post("")
async def create_source(req: SourceCreate):
    """Add a new source to the global library."""
    from database import async_session
    from models import Source

    async with async_session() as session:
        source = Source(
            type=req.type,
            name=req.name,
            config=json.dumps(req.config),
            category_tags=json.dumps(req.category_tags),
            fetch_interval_hours=req.fetch_interval_hours,
            active=True,
        )
        session.add(source)
        await session.commit()
        return _serialize_source(source)


@router.patch("/{source_id}")
async def update_source(source_id: int, req: SourceUpdate):
    """Update a source."""
    from database import async_session
    from models import Source
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return {"error": "Source not found"}

        if req.name is not None:
            source.name = req.name
        if req.config is not None:
            source.config = json.dumps(req.config)
        if req.category_tags is not None:
            source.category_tags = json.dumps(req.category_tags)
        if req.active is not None:
            source.active = req.active
        if req.fetch_interval_hours is not None:
            source.fetch_interval_hours = req.fetch_interval_hours

        await session.commit()
        return _serialize_source(source)


@router.delete("/{source_id}")
async def delete_source(source_id: int):
    """Delete a source from the library."""
    from database import async_session
    from models import Source
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            return {"error": "Source not found"}
        await session.delete(source)
        await session.commit()
        return {"deleted": source_id}


# ── Org subscriptions ─────────────────────────────────────────────────────────

@router.get("/subscriptions")
async def get_org_subscriptions(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get all sources with subscription status for the current org."""
    from database import async_session
    from models import Source, OrgSource
    from sqlalchemy import select

    org_id = dl.org_id

    async with async_session() as session:
        # All active sources
        sources_res = await session.execute(
            select(Source).where(Source.active == True).order_by(Source.type, Source.name)
        )
        all_sources = sources_res.scalars().all()

        # This org's subscriptions
        sub_res = await session.execute(
            select(OrgSource).where(OrgSource.org_id == org_id)
        )
        subs = {s.source_id: s.enabled for s in sub_res.scalars().all()}

        result = []
        for s in all_sources:
            d = _serialize_source(s)
            d["subscribed"] = bool(subs.get(s.id, False))
            result.append(d)

        return result


@router.post("/subscriptions")
async def toggle_subscription(req: OrgSourceToggle, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Subscribe or unsubscribe the current org from a source."""
    from database import async_session
    from models import OrgSource
    from sqlalchemy import select

    org_id = dl.org_id
    if not org_id:
        return {"error": "No org selected"}

    async with async_session() as session:
        result = await session.execute(
            select(OrgSource).where(
                OrgSource.org_id == org_id,
                OrgSource.source_id == req.source_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.enabled = req.enabled
        else:
            sub = OrgSource(
                org_id=org_id,
                source_id=req.source_id,
                enabled=req.enabled,
            )
            session.add(sub)

        await session.commit()
        return {"source_id": req.source_id, "enabled": req.enabled}


@router.post("/subscriptions/bulk")
async def bulk_subscribe(source_ids: list[int], dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Subscribe the current org to multiple sources at once."""
    from database import async_session
    from models import OrgSource
    from sqlalchemy import select

    org_id = dl.org_id
    if not org_id:
        return {"error": "No org selected"}

    async with async_session() as session:
        for source_id in source_ids:
            result = await session.execute(
                select(OrgSource).where(
                    OrgSource.org_id == org_id,
                    OrgSource.source_id == source_id,
                )
            )
            existing = result.scalar_one_or_none()
            if not existing:
                session.add(OrgSource(org_id=org_id, source_id=source_id, enabled=True))

        await session.commit()
        return {"subscribed": len(source_ids)}


# ── Sweep ─────────────────────────────────────────────────────────────────────

@router.post("/sweep")
async def trigger_sweep(req: SweepRequest = SweepRequest()):
    """Trigger the global sweep — crawl sources, embed, dedup, store raw_signals."""
    from services.sweep import run_sweep
    result = await run_sweep(source_ids=req.source_ids)
    return result


# ── Per-org SIGINT feed ───────────────────────────────────────────────────────

@router.get("/feed")
async def get_sigint_feed(
    limit: int = Query(40),
    min_score: float = Query(None),
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """Return raw_signals scored for relevance to the current org.

    Signals are ranked by cosine similarity to the org's fingerprint.
    Sources the org isn't subscribed to are excluded.
    """
    from services.sweep import get_org_feed

    org_id = dl.org_id
    if not org_id:
        return {"error": "No org selected"}

    return await get_org_feed(org_id=org_id, limit=limit, min_score=min_score)


@router.post("/fingerprint/rebuild")
async def rebuild_fingerprint(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Rebuild the org's embedding fingerprint from current settings."""
    from services.sweep import rebuild_org_fingerprint

    org_id = dl.org_id
    if not org_id:
        return {"error": "No org selected"}

    ok = await rebuild_org_fingerprint(org_id)
    if ok:
        return {"status": "rebuilt", "org_id": org_id}
    return {"error": "Failed to build fingerprint — check VOYAGE_API_KEY and org settings"}


@router.get("/fingerprint")
async def get_fingerprint(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get the current org's fingerprint metadata."""
    from database import async_session
    from models import OrgFingerprint
    from sqlalchemy import select

    org_id = dl.org_id
    if not org_id:
        return {"error": "No org selected"}

    async with async_session() as session:
        result = await session.execute(
            select(OrgFingerprint).where(OrgFingerprint.org_id == org_id)
        )
        fp = result.scalar_one_or_none()
        if not fp:
            return {"exists": False}
        return {
            "exists": True,
            "fingerprint_text": fp.fingerprint_text,
            "embedding_model": fp.embedding_model,
            "updated_at": fp.updated_at.isoformat() if fp.updated_at else None,
        }


# ── Recommended sources ───────────────────────────────────────────────────────

@router.get("/recommended")
async def get_recommended_sources(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return recommended sources for the current org based on their industry/topics.

    Matches org's category tags against source category_tags.
    Falls back to returning all active sources if no org context.
    """
    from database import async_session
    from models import Source, OrgSource, Setting
    from sqlalchemy import select

    org_id = dl.org_id

    async with async_session() as session:
        # Get org topics/industry
        org_tags = set()
        if org_id:
            settings_res = await session.execute(
                select(Setting).where(
                    Setting.org_id == org_id,
                    Setting.key.in_(["onboard_industry", "onboard_topics"]),
                )
            )
            for s in settings_res.scalars().all():
                if s.key == "onboard_industry" and s.value:
                    org_tags.add(s.value.lower())
                elif s.key == "onboard_topics" and s.value:
                    try:
                        for t in json.loads(s.value):
                            org_tags.add(t.lower())
                    except Exception:
                        pass

        # Get already-subscribed source IDs
        subscribed_ids = set()
        if org_id:
            sub_res = await session.execute(
                select(OrgSource.source_id).where(
                    OrgSource.org_id == org_id, OrgSource.enabled == True
                )
            )
            subscribed_ids = {r[0] for r in sub_res.fetchall()}

        # Score sources by tag overlap
        sources_res = await session.execute(
            select(Source).where(Source.active == True)
        )
        all_sources = sources_res.scalars().all()

        scored = []
        for s in all_sources:
            if s.id in subscribed_ids:
                continue
            try:
                source_tags = set(t.lower() for t in json.loads(s.category_tags or "[]"))
            except Exception:
                source_tags = set()

            overlap = len(org_tags & source_tags) if org_tags else 0
            scored.append((overlap, s))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [_serialize_source(s) for _, s in scored[:20]]


# ── Seed default sources ──────────────────────────────────────────────────────

DEFAULT_SOURCES = [
    # Reddit
    {"type": "reddit", "name": "r/technology", "config": {"subreddit": "technology"}, "category_tags": ["tech", "general"]},
    {"type": "reddit", "name": "r/programming", "config": {"subreddit": "programming"}, "category_tags": ["tech", "engineering", "software"]},
    {"type": "reddit", "name": "r/devops", "config": {"subreddit": "devops"}, "category_tags": ["devops", "infrastructure", "engineering"]},
    {"type": "reddit", "name": "r/MachineLearning", "config": {"subreddit": "MachineLearning"}, "category_tags": ["ai", "ml", "research"]},
    {"type": "reddit", "name": "r/artificial", "config": {"subreddit": "artificial"}, "category_tags": ["ai", "general"]},
    {"type": "reddit", "name": "r/entrepreneur", "config": {"subreddit": "entrepreneur"}, "category_tags": ["startup", "business"]},
    {"type": "reddit", "name": "r/SaaS", "config": {"subreddit": "SaaS"}, "category_tags": ["saas", "startup", "business"]},
    {"type": "reddit", "name": "r/apis", "config": {"subreddit": "apis"}, "category_tags": ["api", "integration", "developer"]},
    # Hacker News
    {"type": "hackernews", "name": "HN: artificial intelligence", "config": {"keyword": "artificial intelligence"}, "category_tags": ["ai", "tech"]},
    {"type": "hackernews", "name": "HN: API", "config": {"keyword": "API"}, "category_tags": ["api", "developer", "integration"]},
    {"type": "hackernews", "name": "HN: developer tools", "config": {"keyword": "developer tools"}, "category_tags": ["developer", "tools", "engineering"]},
    {"type": "hackernews", "name": "HN: SaaS", "config": {"keyword": "SaaS"}, "category_tags": ["saas", "startup", "business"]},
    {"type": "hackernews", "name": "HN: open source", "config": {"keyword": "open source"}, "category_tags": ["open source", "engineering"]},
    {"type": "hackernews", "name": "HN: security", "config": {"keyword": "security"}, "category_tags": ["security", "enterprise"]},
    {"type": "hackernews", "name": "HN: LLM", "config": {"keyword": "LLM"}, "category_tags": ["ai", "llm", "ml"]},
    {"type": "hackernews", "name": "HN: enterprise software", "config": {"keyword": "enterprise software"}, "category_tags": ["enterprise", "saas"]},
    # RSS
    {"type": "rss", "name": "TechCrunch", "config": {"url": "https://techcrunch.com/feed/"}, "category_tags": ["tech", "startup", "general"]},
    {"type": "rss", "name": "The Verge", "config": {"url": "https://www.theverge.com/rss/index.xml"}, "category_tags": ["tech", "general"]},
    {"type": "rss", "name": "Hacker News Front Page", "config": {"url": "https://hnrss.org/frontpage"}, "category_tags": ["tech", "general", "engineering"]},
    {"type": "rss", "name": "InfoQ", "config": {"url": "https://www.infoq.com/feed/"}, "category_tags": ["engineering", "enterprise", "architecture"]},
    {"type": "rss", "name": "AWS Blog", "config": {"url": "https://aws.amazon.com/blogs/aws/feed/"}, "category_tags": ["cloud", "infrastructure", "devops"]},
    {"type": "rss", "name": "Google AI Blog", "config": {"url": "https://blog.google/technology/ai/rss/"}, "category_tags": ["ai", "research", "ml"]},
    {"type": "rss", "name": "OpenAI Blog", "config": {"url": "https://openai.com/blog/rss/"}, "category_tags": ["ai", "llm", "research"]},
]


@router.post("/seed")
async def seed_default_sources():
    """Seed the source library with default sources. Idempotent — skips existing."""
    from database import async_session
    from models import Source
    from sqlalchemy import select

    async with async_session() as session:
        added = 0
        for s in DEFAULT_SOURCES:
            # Check if name already exists
            existing = await session.execute(
                select(Source).where(Source.name == s["name"])
            )
            if existing.scalar_one_or_none():
                continue

            source = Source(
                type=s["type"],
                name=s["name"],
                config=json.dumps(s["config"]),
                category_tags=json.dumps(s["category_tags"]),
                active=True,
                fetch_interval_hours=24,
            )
            session.add(source)
            added += 1

        await session.commit()
        return {"seeded": added, "total_defaults": len(DEFAULT_SOURCES)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize_source(s) -> dict:
    config = {}
    try:
        config = json.loads(s.config) if s.config else {}
    except Exception:
        pass
    tags = []
    try:
        tags = json.loads(s.category_tags) if s.category_tags else []
    except Exception:
        pass
    return {
        "id": s.id,
        "type": s.type,
        "name": s.name,
        "config": config,
        "category_tags": tags,
        "active": s.active,
        "fetch_interval_hours": s.fetch_interval_hours,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
