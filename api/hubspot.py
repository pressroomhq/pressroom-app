"""HubSpot integration endpoints — connect, sync blog posts, push drafts, list contacts."""

import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.hubspot import HubSpotClient, HubSpotError

log = logging.getLogger("pressroom.hubspot")

router = APIRouter(prefix="/api/hubspot", tags=["hubspot"])

SETTING_KEY = "hubspot_api_key"


# ── Request models ──

class ConnectRequest(BaseModel):
    api_key: str


class PublishRequest(BaseModel):
    content_id: int


# ── Helpers ──

async def _get_client(dl: DataLayer) -> HubSpotClient | None:
    """Build a HubSpotClient from the stored API key, or None if not configured."""
    key = await dl.get_setting(SETTING_KEY)
    if not key:
        return None
    return HubSpotClient(api_key=key)


def _strip_html(html: str) -> str:
    """Rough HTML-to-text for imported blog body previews."""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


# ── Endpoints ──

@router.post("/connect")
async def connect(req: ConnectRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Save a HubSpot private app token and verify the connection."""
    api_key = req.api_key.strip()
    if not api_key:
        return {"error": "API key is required"}

    # Test before saving
    client = HubSpotClient(api_key=api_key)
    result = await client.test_connection()
    if not result.get("connected"):
        return {"error": f"Connection failed: {result.get('error', 'unknown')}"}

    await dl.set_setting(SETTING_KEY, api_key)
    await dl.commit()
    log.info("HubSpot connected — portal %s", result.get("portal_id"))
    return {
        "connected": True,
        "portal_id": result.get("portal_id"),
        "hub_domain": result.get("hub_domain", ""),
    }


@router.get("/status")
async def status(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Check whether HubSpot is connected and the token is valid."""
    client = await _get_client(dl)
    if not client:
        return {"connected": False, "configured": False}

    result = await client.test_connection()
    return {
        "connected": result.get("connected", False),
        "configured": True,
        "portal_id": result.get("portal_id"),
        "hub_domain": result.get("hub_domain", ""),
        "error": result.get("error"),
    }


@router.get("/blogs")
async def list_blogs(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List blog posts from HubSpot CMS."""
    client = await _get_client(dl)
    if not client:
        return {"error": "HubSpot not connected"}

    try:
        posts = await client.list_blog_posts(limit=50)
        return {"posts": posts, "count": len(posts)}
    except HubSpotError as e:
        return {"error": str(e)}


@router.post("/publish")
async def publish_to_hubspot(req: PublishRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Push a Pressroom content item to HubSpot as a blog draft."""
    client = await _get_client(dl)
    if not client:
        return {"error": "HubSpot not connected"}

    # Fetch the content item
    content = await dl.get_content(req.content_id)
    if not content:
        return {"error": f"Content item {req.content_id} not found"}

    if content.get("channel") != "blog":
        return {"error": f"Content #{req.content_id} is channel '{content.get('channel')}', expected 'blog'"}

    title = content.get("headline", "Untitled")
    body = content.get("body", "")

    # Wrap plain text in basic HTML paragraphs if it doesn't look like HTML
    if "<p>" not in body and "<div>" not in body:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        body = "".join(f"<p>{p}</p>" for p in paragraphs)

    # Generate a slug from the headline
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]

    try:
        result = await client.create_blog_draft(title=title, body=body, slug=slug)
        log.info("Pushed content #%d to HubSpot as draft %s", req.content_id, result.get("id"))
        return {
            "published": True,
            "hubspot_post": result,
            "content_id": req.content_id,
        }
    except HubSpotError as e:
        return {"error": str(e)}


@router.post("/sync")
async def sync_from_hubspot(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Pull recent blog posts from HubSpot into Pressroom as approved blog content.

    This gives the content engine context about what's already been published,
    preventing topic repetition and building voice memory.
    """
    client = await _get_client(dl)
    if not client:
        return {"error": "HubSpot not connected"}

    try:
        posts = await client.list_blog_posts(limit=50)
    except HubSpotError as e:
        return {"error": str(e)}

    imported = 0
    skipped = 0

    for post in posts:
        # Fetch full post body
        try:
            full = await client.get_blog_post(post["id"])
        except HubSpotError:
            skipped += 1
            continue

        body_html = full.get("body", "")
        body_text = _strip_html(body_html)

        if not body_text or len(body_text) < 50:
            skipped += 1
            continue

        # Store as approved blog content for engine context
        await dl.save_content({
            "channel": "blog",
            "status": "approved",
            "headline": full.get("title", post.get("title", "Untitled")),
            "body": body_text[:5000],
            "body_raw": body_html[:10000],
            "author": full.get("author_name", "hubspot-import"),
        })
        imported += 1

    await dl.commit()
    log.info("HubSpot sync: imported %d, skipped %d", imported, skipped)
    return {"imported": imported, "skipped": skipped, "total_found": len(posts)}


@router.get("/contacts")
async def list_contacts(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List CRM contacts from HubSpot (for future email feature)."""
    client = await _get_client(dl)
    if not client:
        return {"error": "HubSpot not connected"}

    try:
        contacts = await client.list_contacts(limit=100)
        return {"contacts": contacts, "count": len(contacts)}
    except HubSpotError as e:
        return {"error": str(e)}


@router.delete("/disconnect")
async def disconnect(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Remove the HubSpot API key."""
    await dl.set_setting(SETTING_KEY, "")
    await dl.commit()
    log.info("HubSpot disconnected")
    return {"disconnected": True}
