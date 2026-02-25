"""Content endpoints — approval queue, content management, scheduling."""

import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc

from database import get_data_layer
from models import ContentPerformance
from services.data_layer import DataLayer
from services.publisher import publish_single

router = APIRouter(prefix="/api/content", tags=["content"])


class ActionRequest(BaseModel):
    action: str  # "approve" | "spike" | "publish"


class ScheduleRequest(BaseModel):
    scheduled_at: str  # ISO 8601 datetime string


@router.get("")
async def list_content(
    status: str | None = None,
    limit: int = 50,
    story_id: int | None = None,
    dl: DataLayer = Depends(get_data_layer),
):
    return await dl.list_content(status=status, limit=limit, story_id=story_id)


@router.get("/queue")
async def approval_queue(dl: DataLayer = Depends(get_data_layer)):
    """The editor's desk — all queued content."""
    return await dl.list_content(status="queued")


@router.get("/scheduled")
async def list_scheduled(dl: DataLayer = Depends(get_data_layer)):
    """List all scheduled (approved, not yet published) content with their scheduled times."""
    return await dl.list_scheduled_content()


@router.get("/published/performance")
async def list_published_performance(dl: DataLayer = Depends(get_data_layer)):
    """Get latest performance snapshot for all published content with post_ids.

    Returns a map of content_id -> latest metrics for the performance column in the UI.
    """
    from sqlalchemy import func, and_

    latest_sub = (
        select(
            ContentPerformance.content_id,
            func.max(ContentPerformance.fetched_at).label("max_fetched"),
        )
        .group_by(ContentPerformance.content_id)
        .subquery()
    )

    result = await dl.db.execute(
        select(ContentPerformance).join(
            latest_sub,
            and_(
                ContentPerformance.content_id == latest_sub.c.content_id,
                ContentPerformance.fetched_at == latest_sub.c.max_fetched,
            ),
        )
    )
    rows = result.scalars().all()

    return {
        str(r.content_id): {
            "impressions": r.impressions,
            "clicks": r.clicks,
            "likes": r.likes,
            "comments": r.comments,
            "shares": r.shares,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
        }
        for r in rows
    }


@router.get("/{content_id}")
async def get_content(content_id: int, dl: DataLayer = Depends(get_data_layer)):
    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")
    return c


@router.post("/{content_id}/schedule")
async def schedule_content(content_id: int, req: ScheduleRequest, dl: DataLayer = Depends(get_data_layer)):
    """Schedule approved content for future publishing."""
    try:
        scheduled_dt = datetime.datetime.fromisoformat(req.scheduled_at)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid ISO 8601 datetime for scheduled_at")

    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")

    result = await dl.schedule_content(content_id, scheduled_dt)
    if not result:
        raise HTTPException(status_code=404, detail="Content not found")

    await dl.commit()
    return result


@router.post("/{content_id}/action")
async def content_action(content_id: int, req: ActionRequest, dl: DataLayer = Depends(get_data_layer)):
    """Approve or spike a piece of content."""
    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")

    if req.action not in ("approve", "spike", "publish", "unpublish", "unapprove"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    status_map = {"approve": "approved", "spike": "spiked", "publish": "published", "unpublish": "approved", "unapprove": "queued"}
    new_status = status_map[req.action]
    result = await dl.update_content_status(content_id, new_status)

    # When content is spiked, increment spike count on each source signal
    if req.action == "spike":
        source_ids = (c.get("source_signal_ids", "") or "").strip()
        if source_ids:
            for sid in source_ids.split(","):
                sid = sid.strip()
                if sid and sid.isdigit():
                    await dl.increment_signal_spikes(int(sid))

    await dl.commit()
    return result


@router.post("/{content_id}/publish")
async def publish_content_item(content_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Publish a single content item via its channel's API. Only publishes THIS item."""
    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")

    if c.get("status") not in ("approved", "queued"):
        raise HTTPException(status_code=400, detail=f"Content is {c.get('status')}, not approved/queued")

    settings = await dl.get_all_settings()
    result = await publish_single(c, settings, dl=dl)

    if result.get("success") or result.get("status") in ("manual", "no_destination"):
        # Persist platform post ID and URL for performance tracking
        extra = {}
        post_id = result.get("id") or result.get("post_id") or ""
        post_url = result.get("url") or result.get("devto_url") or ""
        if post_id:
            extra["post_id"] = str(post_id)
        if post_url:
            extra["post_url"] = str(post_url)
        await dl.update_content_status(content_id, "published", **extra)
        await dl.commit()

    return {"id": content_id, "channel": c.get("channel"), "result": result}


@router.get("/{content_id}/performance")
async def get_content_performance(content_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Get performance metrics for a published content item."""
    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")

    result = await dl.db.execute(
        select(ContentPerformance)
        .where(ContentPerformance.content_id == content_id)
        .order_by(desc(ContentPerformance.fetched_at))
        .limit(30)
    )
    rows = result.scalars().all()

    latest = rows[0] if rows else None
    return {
        "content_id": content_id,
        "post_id": c.get("post_id", ""),
        "post_url": c.get("post_url", ""),
        "latest": {
            "impressions": latest.impressions,
            "clicks": latest.clicks,
            "likes": latest.likes,
            "comments": latest.comments,
            "shares": latest.shares,
            "fetched_at": latest.fetched_at.isoformat() if latest.fetched_at else None,
        } if latest else None,
        "history": [
            {
                "impressions": r.impressions, "clicks": r.clicks,
                "likes": r.likes, "comments": r.comments, "shares": r.shares,
                "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in reversed(rows)
        ],
    }


@router.post("/{content_id}/fetch-performance")
async def fetch_content_performance_now(content_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Manually trigger a performance fetch for a single content item."""
    c = await dl.get_content(content_id)
    if not c:
        raise HTTPException(status_code=404, detail="Content not found")
    if not c.get("post_id"):
        return {"error": "No post_id stored — content may not have been published via API"}

    settings = await dl.get_all_settings()
    channel = c.get("channel", "")
    stats = {}

    from services import social_auth
    if channel == "linkedin":
        token = settings.get("linkedin_access_token", "")
        if token:
            stats = await social_auth.linkedin_post_stats(token, c["post_id"])
    elif channel == "devto":
        api_key = settings.get("devto_api_key", "")
        if api_key:
            stats = await social_auth.devto_post_stats(api_key, c["post_id"])
    elif channel == "facebook":
        page_token = settings.get("facebook_page_token", "")
        if page_token:
            stats = await social_auth.facebook_post_stats(page_token, c["post_id"])

    if stats and any(v > 0 for v in stats.values()):
        perf = ContentPerformance(
            content_id=content_id,
            impressions=stats.get("impressions", 0),
            clicks=stats.get("clicks", 0),
            likes=stats.get("likes", 0),
            comments=stats.get("comments", 0),
            shares=stats.get("shares", 0),
            fetched_at=datetime.datetime.utcnow(),
        )
        dl.db.add(perf)
        await dl.commit()

    return {"content_id": content_id, "channel": channel, "stats": stats}
