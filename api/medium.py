"""Medium API — publish content as Medium drafts."""

import os
import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import get_data_layer
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/medium", tags=["medium"])

MEDIUM_TOKEN = os.getenv("MEDIUM_TOKEN", "")
MEDIUM_API = "https://api.medium.com/v1"


class PublishRequest(BaseModel):
    content_id: int | None = None
    title: str = ""
    body: str = ""
    tags: list[str] = ["technology", "marketing", "ai"]


@router.post("/publish")
async def publish_to_medium(req: PublishRequest, dl: DataLayer = Depends(get_data_layer)):
    """Publish content as a Medium draft. Always creates as draft — Captain reviews before making public."""
    if not MEDIUM_TOKEN:
        return {"error": "MEDIUM_TOKEN not configured. Set it as an environment variable."}

    title = req.title
    body = req.body

    # If content_id provided, fetch from DB
    if req.content_id:
        content = await dl.get_content(req.content_id)
        if not content:
            return {"error": f"Content {req.content_id} not found."}
        title = content.get("headline", "") or title
        body = content.get("body", "") or body

    if not title or not body:
        return {"error": "Title and body are required."}

    # Add Pressroom credit
    body_with_credit = f"{body}\n\n---\n*Written with [Pressroom HQ](https://pressroomhq.com)*"

    headers = {
        "Authorization": f"Bearer {MEDIUM_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get user ID
            me_resp = await client.get(f"{MEDIUM_API}/me", headers=headers)
            me_resp.raise_for_status()
            user_id = me_resp.json().get("data", {}).get("id")
            if not user_id:
                return {"error": "Could not retrieve Medium user ID."}

            # Create post as draft
            payload = {
                "title": title,
                "contentFormat": "markdown",
                "content": body_with_credit,
                "tags": req.tags[:5],  # Medium allows max 5 tags
                "publishStatus": "draft",
            }

            resp = await client.post(
                f"{MEDIUM_API}/users/{user_id}/posts",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            return {
                "medium_url": data.get("url", ""),
                "post_id": data.get("id", ""),
                "status": "draft",
                "title": data.get("title", title),
            }

    except httpx.HTTPStatusError as e:
        log.error("Medium publish failed: %s — %s", e.response.status_code, e.response.text)
        return {"error": f"Medium API error: {e.response.status_code}"}
    except Exception as e:
        log.error("Medium publish failed: %s", e)
        return {"error": f"Medium publish failed: {str(e)}"}
