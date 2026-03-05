"""GitHub webhook — release events trigger full content cascade."""

import datetime
import hashlib
import hmac
from fastapi import APIRouter, Request, Depends, HTTPException

from config import settings
from database import get_data_layer
from models import ContentChannel
from services.data_layer import DataLayer
from services.engine import generate_brief, generate_all_content
from services.humanizer import humanize

router = APIRouter(prefix="/api/webhook", tags=["webhook"])


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (HMAC-SHA256)."""
    if not secret:
        return True
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(request: Request, dl: DataLayer = Depends(get_data_layer)):
    """Handle GitHub webhook events. Releases trigger the full content cascade."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    webhook_secret = getattr(settings, "github_webhook_secret", "")

    if webhook_secret and not verify_signature(body, signature, webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event == "ping":
        return {"status": "pong"}

    if event == "release":
        return await handle_release(payload, dl)

    if event == "push":
        return await handle_push(payload, dl)

    return {"status": "ignored", "event": event}


async def handle_release(payload: dict, dl: DataLayer) -> dict:
    """GitHub release → full content cascade."""
    release = payload.get("release", {})
    repo = payload.get("repository", {})
    repo_name = repo.get("full_name", "unknown/unknown")

    tag = release.get("tag_name", "")
    name = release.get("name", tag)
    body = release.get("body", "")
    url = release.get("html_url", "")

    # Save as signal
    signal = await dl.save_signal({
        "type": "github_release",
        "source": repo_name,
        "title": f"{repo_name} — {tag}: {name}",
        "body": body[:2000],
        "url": url,
        "raw_data": str(payload)[:5000],
    })

    signal_dicts = [{
        "type": "github_release",
        "source": repo_name,
        "title": f"{repo_name} — {tag}: {name}",
        "body": body[:1000],
    }]

    # Load voice + memory context
    voice = await dl.get_voice_settings()
    memory = await dl.get_memory_context()

    brief_data = await generate_brief(signal_dicts, memory=memory, voice_settings=voice)
    brief = await dl.save_brief({
        "date": str(datetime.date.today()),
        "summary": brief_data["summary"],
        "angle": brief_data["angle"],
        "signal_ids": str(signal.get("id", "")),
    })

    # Full cascade — all channels
    all_channels = [
        ContentChannel.linkedin,
        ContentChannel.x_thread,
        ContentChannel.release_email,
        ContentChannel.blog,
        ContentChannel.newsletter,
    ]

    content_items = await generate_all_content(
        brief_data["summary"], signal_dicts, all_channels,
        memory=memory, voice_settings=voice, dl=dl,
    )

    saved = []
    for item in content_items:
        raw = item["body"]
        clean = humanize(raw)
        result = await dl.save_content({
            "brief_id": brief.get("id"),
            "signal_id": signal.get("id"),
            "channel": item["channel"],
            "status": "queued",
            "headline": item["headline"],
            "body": clean,
            "body_raw": raw,
            "author": "company",
        })
        saved.append(result)

    await dl.commit()

    return {
        "status": "cascade_triggered",
        "trigger": f"release:{tag}",
        "repo": repo_name,
        "content_generated": len(saved),
        "items": [{"channel": c.get("channel", ""), "headline": c.get("headline", "")} for c in saved],
    }


async def handle_push(payload: dict, dl: DataLayer) -> dict:
    """GitHub push → save as signal (doesn't trigger full cascade)."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    commits = payload.get("commits", [])
    ref = payload.get("ref", "")

    if not commits:
        return {"status": "ignored", "reason": "no commits"}

    messages = [c["message"].split("\n")[0] for c in commits[:10]]
    await dl.save_signal({
        "type": "github_commit",
        "source": repo,
        "title": f"{repo} — {len(commits)} commits to {ref.split('/')[-1]}",
        "body": "\n".join(f"• {m}" for m in messages),
        "url": payload.get("compare", ""),
        "raw_data": str(commits[:3])[:5000],
    })
    await dl.commit()

    return {"status": "signal_saved", "commits": len(commits)}
