"""Content endpoints — approval queue, content management, scheduling."""

import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/content", tags=["content"])


class ActionRequest(BaseModel):
    action: str  # "approve" | "spike"


class ScheduleRequest(BaseModel):
    scheduled_at: str  # ISO 8601 datetime string


@router.get("")
async def list_content(
    status: str | None = None,
    limit: int = 50,
    story_id: int | None = None,
    dl: DataLayer = Depends(get_data_layer),
):
    # Desk view excludes story-linked content unless explicitly requesting by story_id
    exclude = story_id is None
    return await dl.list_content(status=status, limit=limit, story_id=story_id, exclude_stories=exclude)


@router.get("/queue")
async def approval_queue(dl: DataLayer = Depends(get_data_layer)):
    """The editor's desk — queued content NOT linked to a story."""
    return await dl.list_content(status="queued", exclude_stories=True)


@router.get("/scheduled")
async def list_scheduled(dl: DataLayer = Depends(get_data_layer)):
    """List all scheduled (approved, not yet published) content with their scheduled times."""
    return await dl.list_scheduled_content()


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

    if req.action not in ("approve", "spike"):
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    new_status = "approved" if req.action == "approve" else "spiked"
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
