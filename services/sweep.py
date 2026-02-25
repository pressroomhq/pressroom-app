"""Sweep service — global source crawl into raw_signals.

The sweep runs on a schedule (or on demand). It crawls all active Sources,
embeds each result, deduplicates against recent raw_signals, and stores
new signals in raw_signals. No org context at this stage.

Per-org relevance is computed separately when an org requests its feed:
  cosine(raw_signal.embedding, org_fingerprint.embedding) >= RELEVANCE_THRESHOLD

This is the moat: sources crawled once, relevance computed per-org cheaply.
"""

import json
import datetime
import logging
from typing import Optional

import httpx
import feedparser

log = logging.getLogger("pressroom")

from services.embeddings import (
    embed,
    embed_batch,
    serialize as emb_serialize,
    deserialize as emb_deserialize,
    is_duplicate,
    VOYAGE_MODEL,
)


# ── Fetchers ─────────────────────────────────────────────────────────────────

async def _fetch_reddit(config: dict) -> list[dict]:
    """Fetch hot posts from a subreddit."""
    subreddit = config.get("subreddit", "")
    if not subreddit:
        return []
    limit = config.get("limit", 10)
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "PressroomHQ/1.0 SIGINT Sweep"},
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            results = []
            for p in posts:
                d = p.get("data", {})
                if d.get("is_self") is False or d.get("score", 0) > 10:
                    results.append({
                        "title": d.get("title", ""),
                        "body": d.get("selftext", "")[:500],
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "raw_data": json.dumps({
                            "score": d.get("score"),
                            "comments": d.get("num_comments"),
                            "author": d.get("author"),
                            "subreddit": subreddit,
                        }),
                    })
            return results
    except Exception:
        return []


async def _fetch_hackernews(config: dict) -> list[dict]:
    """Search HN via Algolia for a keyword."""
    keyword = config.get("keyword", "")
    if not keyword:
        return []
    limit = config.get("limit", 8)
    url = f"https://hn.algolia.com/api/v1/search?query={keyword}&tags=story&hitsPerPage={limit}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for hit in data.get("hits", []):
                results.append({
                    "title": hit.get("title", ""),
                    "body": hit.get("story_text") or hit.get("comment_text") or "",
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    "raw_data": json.dumps({
                        "points": hit.get("points"),
                        "num_comments": hit.get("num_comments"),
                        "author": hit.get("author"),
                        "keyword": keyword,
                    }),
                })
            return results
    except Exception:
        return []


async def _fetch_rss(config: dict) -> list[dict]:
    """Parse an RSS or Atom feed."""
    feed_url = config.get("url", "")
    if not feed_url:
        return []
    limit = config.get("limit", 10)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": "PressroomHQ/1.0"})
            raw = resp.text

        feed = feedparser.parse(raw)
        results = []
        for entry in feed.entries[:limit]:
            title = entry.get("title", "")
            body = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
            # Strip HTML tags from body
            import re
            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()[:600]
            link = entry.get("link", "")
            results.append({
                "title": title,
                "body": body,
                "url": link,
                "raw_data": json.dumps({
                    "feed_url": feed_url,
                    "published": entry.get("published", ""),
                    "author": entry.get("author", ""),
                }),
            })
        return results
    except Exception:
        return []


async def _fetch_x_search(config: dict) -> list[dict]:
    """Placeholder for X/Twitter search. Returns empty until API key is set."""
    # X API v2 requires Bearer token. Config: {query: "...", bearer_token: "..."}
    # Implementing the stub — wire up when TWITTER_BEARER_TOKEN is available.
    bearer = config.get("bearer_token", "")
    if not bearer:
        return []
    query = config.get("query", "")
    if not query:
        return []
    try:
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": f"{query} -is:retweet lang:en",
            "max_results": 10,
            "tweet.fields": "public_metrics,author_id,created_at",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {bearer}"})
            resp.raise_for_status()
            data = resp.json()
            results = []
            for tweet in data.get("data", []):
                results.append({
                    "title": tweet.get("text", "")[:200],
                    "body": tweet.get("text", ""),
                    "url": f"https://twitter.com/i/web/status/{tweet['id']}",
                    "raw_data": json.dumps(tweet.get("public_metrics", {})),
                })
            return results
    except Exception:
        return []


FETCHERS = {
    "reddit": _fetch_reddit,
    "hackernews": _fetch_hackernews,
    "rss": _fetch_rss,
    "x_search": _fetch_x_search,
    "trends": _fetch_rss,   # trends can be an RSS feed (Google Trends RSS, etc.)
}


# ── Sweep orchestration ───────────────────────────────────────────────────────

async def sweep_source(source, session) -> dict:
    """Crawl one source, embed results, dedup, save new raw_signals.

    Returns {source_id, source_name, fetched, new, dupes, errors}
    """
    from models import RawSignal
    from sqlalchemy import select

    log.info("[sweep] Sweeping source: %s (%s, id=%s)", source.name, source.type, source.id)

    config = {}
    try:
        config = json.loads(source.config) if source.config else {}
    except Exception:
        pass

    fetcher = FETCHERS.get(source.type)
    if not fetcher:
        log.warning("[sweep] Unknown source type '%s' for %s — skipping", source.type, source.name)
        return {"source_id": source.id, "source_name": source.name, "fetched": 0, "new": 0, "dupes": 0, "errors": ["unknown source type"]}

    # Fetch raw items
    try:
        items = await fetcher(config)
        log.info("[sweep] %s: fetched %d items", source.name, len(items))
    except Exception as e:
        log.error("[sweep] %s: fetch failed — %s", source.name, e)
        return {"source_id": source.id, "source_name": source.name, "fetched": 0, "new": 0, "dupes": 0, "errors": [str(e)]}

    if not items:
        log.debug("[sweep] %s: no items returned", source.name)
        return {"source_id": source.id, "source_name": source.name, "fetched": 0, "new": 0, "dupes": 0, "errors": []}

    # URL dedup — skip URLs already in raw_signals
    urls = [i["url"] for i in items if i.get("url")]
    if urls:
        existing_url_res = await session.execute(
            select(RawSignal.url).where(RawSignal.url.in_(urls))
        )
        existing_urls = set(r[0] for r in existing_url_res.fetchall())
        items = [i for i in items if i.get("url") not in existing_urls]

    if not items:
        return {"source_id": source.id, "source_name": source.name, "fetched": len(items), "new": 0, "dupes": len(urls) - len(items), "errors": []}

    # Load recent embeddings for semantic dedup (last 48h)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=48)
    recent_res = await session.execute(
        select(RawSignal.embedding).where(
            RawSignal.fetched_at >= cutoff,
            RawSignal.embedding != "",
        ).limit(500)
    )
    recent_embeddings = [
        emb_deserialize(row[0])
        for row in recent_res.fetchall()
        if row[0]
    ]

    # Embed all items in batch
    log.info("[sweep] %s: embedding %d items...", source.name, len(items))
    texts = [f"{i['title']} {i['body'][:400]}" for i in items]
    embeddings = await embed_batch(texts)

    new_count = 0
    dupe_count = 0

    for item, emb in zip(items, embeddings):
        # Semantic dedup against recent signals
        if emb and is_duplicate(emb, recent_embeddings):
            dupe_count += 1
            continue

        raw = RawSignal(
            source_id=source.id,
            type=source.type,
            source_name=source.name,
            title=item["title"][:500],
            body=item.get("body", "")[:2000],
            url=item.get("url", ""),
            raw_data=item.get("raw_data", "{}"),
            embedding=emb_serialize(emb) if emb else "",
            embedding_model=VOYAGE_MODEL if emb else "",
            fetched_at=datetime.datetime.utcnow(),
        )
        session.add(raw)

        # Add to recent_embeddings so we dedup within this batch too
        if emb:
            recent_embeddings.append(emb)

        new_count += 1

    # Update last_fetched_at on source
    source.last_fetched_at = datetime.datetime.utcnow()
    await session.commit()

    log.info("[sweep] %s: complete — %d new, %d dupes", source.name, new_count, dupe_count)
    return {
        "source_id": source.id,
        "source_name": source.name,
        "fetched": len(items) + dupe_count,
        "new": new_count,
        "dupes": dupe_count,
        "errors": [],
    }


async def run_sweep(source_ids: Optional[list[int]] = None) -> dict:
    """Run sweep across all active sources (or a subset by ID).

    Called by the daily scheduler or POST /api/sources/sweep.
    """
    from database import async_session
    from models import Source
    from sqlalchemy import select

    log.info("=" * 60)
    log.info("[sweep] SWEEP — starting (source_ids=%s)", source_ids or "all active")
    log.info("=" * 60)

    async with async_session() as session:
        query = select(Source).where(Source.active == True)
        if source_ids:
            query = query.where(Source.id.in_(source_ids))
        result = await session.execute(query)
        sources = result.scalars().all()
        log.info("[sweep] Found %d active sources to sweep", len(sources))

        results = []
        for i, source in enumerate(sources):
            log.info("[sweep] >>> Sweeping source %d/%d: %s (%s)", i + 1, len(sources), source.name, source.type)
            result = await sweep_source(source, session)
            results.append(result)

        total_new = sum(r["new"] for r in results)
        total_dupes = sum(r["dupes"] for r in results)

        log.info("[sweep] SWEEP — complete: %d sources swept, %d new signals, %d dupes", len(sources), total_new, total_dupes)
        return {
            "swept": len(sources),
            "total_new": total_new,
            "total_dupes": total_dupes,
            "sources": results,
        }


async def get_org_feed(
    org_id: int,
    limit: int = 40,
    min_score: float = None,
) -> list[dict]:
    """Return raw_signals scored for relevance to an org.

    Loads the org's fingerprint embedding, scores all recent raw signals,
    filters by subscribed sources and relevance threshold, returns ranked list.
    """
    from database import async_session
    from models import RawSignal, OrgFingerprint, OrgSource
    from sqlalchemy import select
    from services.embeddings import RELEVANCE_THRESHOLD, score_relevance

    log.info("[sweep] Building org feed for org_id=%d (limit=%d)", org_id, limit)
    threshold = min_score if min_score is not None else RELEVANCE_THRESHOLD

    async with async_session() as session:
        # Get org fingerprint
        fp_res = await session.execute(
            select(OrgFingerprint).where(OrgFingerprint.org_id == org_id)
        )
        fingerprint = fp_res.scalar_one_or_none()

        if not fingerprint or not fingerprint.embedding:
            log.info("[sweep] No org fingerprint for org_id=%d — returning unscored signals", org_id)
            # No fingerprint yet — return recent signals unscored
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=3)
            raw_res = await session.execute(
                select(RawSignal)
                .where(RawSignal.fetched_at >= cutoff)
                .order_by(RawSignal.fetched_at.desc())
                .limit(limit)
            )
            signals = raw_res.scalars().all()
            return [_serialize_raw_signal(s, score=None) for s in signals]

        org_emb = emb_deserialize(fingerprint.embedding)

        # Get org's subscribed source IDs
        sub_res = await session.execute(
            select(OrgSource.source_id)
            .where(OrgSource.org_id == org_id, OrgSource.enabled == True)
        )
        subscribed_ids = [r[0] for r in sub_res.fetchall()]

        # Get recent raw signals from subscribed sources
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=3)
        query = select(RawSignal).where(RawSignal.fetched_at >= cutoff)
        if subscribed_ids:
            query = query.where(RawSignal.source_id.in_(subscribed_ids))
        query = query.order_by(RawSignal.fetched_at.desc()).limit(300)

        raw_res = await session.execute(query)
        candidates = raw_res.scalars().all()

        # Score each against org fingerprint
        scored = []
        for sig in candidates:
            sig_emb = emb_deserialize(sig.embedding)
            if sig_emb:
                score = score_relevance(sig_emb, org_emb)
            else:
                score = 0.5  # no embedding — include with neutral score
            if score >= threshold:
                scored.append((score, sig))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        log.info("[sweep] Org feed for org_id=%d: %d candidates scored, %d above threshold (%.2f)",
                 org_id, len(candidates), len(scored), threshold)
        return [_serialize_raw_signal(sig, score=score) for score, sig in scored[:limit]]


async def rebuild_org_fingerprint(org_id: int) -> bool:
    """Rebuild and store an org's embedding fingerprint.

    Call this after org settings change or on first onboard.
    """
    log.info("[sweep] Rebuilding org fingerprint for org_id=%d...", org_id)
    from database import async_session
    from models import OrgFingerprint, Setting, Organization
    from sqlalchemy import select
    from services.embeddings import build_org_fingerprint_text, VOYAGE_MODEL

    async with async_session() as session:
        # Load org settings
        settings_res = await session.execute(
            select(Setting).where(Setting.org_id == org_id)
        )
        settings = {s.key: s.value for s in settings_res.scalars().all()}

        org_res = await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_res.scalar_one_or_none()
        if org:
            settings["name"] = org.name
            settings["domain"] = org.domain

        text = build_org_fingerprint_text(settings)
        if not text:
            return False

        emb = await embed(text)
        if not emb:
            return False

        # Upsert fingerprint
        fp_res = await session.execute(
            select(OrgFingerprint).where(OrgFingerprint.org_id == org_id)
        )
        fp = fp_res.scalar_one_or_none()

        if fp:
            fp.fingerprint_text = text
            fp.embedding = emb_serialize(emb)
            fp.embedding_model = VOYAGE_MODEL
            fp.updated_at = datetime.datetime.utcnow()
        else:
            fp = OrgFingerprint(
                org_id=org_id,
                fingerprint_text=text,
                embedding=emb_serialize(emb),
                embedding_model=VOYAGE_MODEL,
                updated_at=datetime.datetime.utcnow(),
            )
            session.add(fp)

        await session.commit()
        log.info("[sweep] Org fingerprint rebuilt for org_id=%d", org_id)
        return True


def _serialize_raw_signal(sig, score: Optional[float]) -> dict:
    return {
        "id": sig.id,
        "source_id": sig.source_id,
        "type": sig.type,
        "source_name": sig.source_name,
        "title": sig.title,
        "body": sig.body,
        "url": sig.url,
        "relevance_score": round(score, 3) if score is not None else None,
        "fetched_at": sig.fetched_at.isoformat() if sig.fetched_at else None,
    }
