"""Email Draft endpoints — compose, preview, and manage email drafts."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.email_composer import compose_email_draft

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/email", tags=["email"])


# ── Request models ──

class ComposeRequest(BaseModel):
    content_id: int


class DraftUpdate(BaseModel):
    subject: str | None = None
    html_body: str | None = None
    text_body: str | None = None
    recipients: list[str] | None = None
    status: str | None = None


# ── Endpoints ──

@router.post("/drafts/compose")
async def compose_draft(req: ComposeRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Compose an email draft from an existing content item."""
    content = await dl.get_content(req.content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    channel = content.get("channel", "")
    if channel not in ("release_email", "newsletter"):
        raise HTTPException(status_code=400, detail=f"Content channel '{channel}' is not an email type")

    # Gather org settings for the template
    org_settings = {}
    if dl.org_id:
        org_data = await dl.get_org(dl.org_id)
        if org_data:
            org_settings["name"] = org_data.get("name", "")
            org_settings["domain"] = org_data.get("domain", "")
        voice = await dl.get_voice_settings()
        org_settings.update(voice)

    # Compose the draft
    draft_data = compose_email_draft(content, org_settings)
    draft_data["content_id"] = req.content_id

    # Save it
    saved = await dl.save_email_draft(draft_data)
    await dl.commit()
    return saved


@router.get("/drafts")
async def list_drafts(
    status: str | None = None,
    limit: int = 20,
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """List email drafts, optionally filtered by status."""
    return await dl.list_email_drafts(status=status, limit=limit)


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get a single email draft with full HTML."""
    draft = await dl.get_email_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return draft


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: int, req: DraftUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update an email draft — subject, html_body, recipients, status."""
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Validate status if provided
    if "status" in updates and updates["status"] not in ("draft", "ready", "sent"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {updates['status']}")

    result = await dl.update_email_draft(draft_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Email draft not found")
    await dl.commit()
    return result


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Delete an email draft."""
    deleted = await dl.delete_email_draft(draft_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Email draft not found")
    await dl.commit()
    return {"deleted": True}


@router.get("/drafts/{draft_id}/preview")
async def preview_draft(draft_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return the HTML body directly for iframe preview."""
    draft = await dl.get_email_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return HTMLResponse(content=draft["html_body"], status_code=200)
