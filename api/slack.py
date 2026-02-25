"""Slack integration endpoints — test, notify, bulk notify.

All endpoints pull slack_webhook_url from org settings.
If it's not configured, they tell you so.
"""

from fastapi import APIRouter, Depends

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.slack_notify import send_content_suggestion, send_pipeline_summary, send_to_slack

router = APIRouter(prefix="/api/slack", tags=["slack"])


async def _get_webhook(dl: DataLayer) -> str | None:
    """Load the Slack webhook URL from org settings."""
    return await dl.get_setting("slack_webhook_url") or None


@router.post("/test")
async def test_webhook(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Send a test message to verify the webhook is working."""
    webhook_url = await _get_webhook(dl)
    if not webhook_url:
        return {"error": "Slack webhook URL not configured. Set slack_webhook_url in settings."}

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Pressroom connected",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Slack notifications are working. Content drafts will show up here when they're ready for review.",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Pressroom test message",
                },
            ],
        },
    ]

    result = await send_to_slack(webhook_url, blocks)
    return result


@router.post("/notify/{content_id}")
async def notify_content(content_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Send a specific content piece as a Slack notification."""
    webhook_url = await _get_webhook(dl)
    if not webhook_url:
        return {"error": "Slack webhook URL not configured. Set slack_webhook_url in settings."}

    content = await dl.get_content(content_id)
    if not content:
        return {"error": f"Content {content_id} not found"}

    # Try to find the assigned team member by author field
    team_member = None
    author = content.get("author", "")
    if author and author != "company":
        members = await dl.list_team_members()
        for m in members:
            if m.get("name", "").lower() == author.lower():
                team_member = m
                break

    result = await send_content_suggestion(webhook_url, content, team_member)
    return {"content_id": content_id, **result}


@router.post("/notify-queue")
async def notify_queue(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Send all queued content as Slack notifications -- one message per item."""
    webhook_url = await _get_webhook(dl)
    if not webhook_url:
        return {"error": "Slack webhook URL not configured. Set slack_webhook_url in settings."}

    queued = await dl.list_content(status="queued")
    if not queued:
        return {"sent": 0, "message": "No queued content to notify about"}

    sent = 0
    errors = []
    for item in queued:
        # Try to resolve team member from author
        team_member = None
        author = item.get("author", "")
        if author and author != "company":
            members = await dl.list_team_members()
            for m in members:
                if m.get("name", "").lower() == author.lower():
                    team_member = m
                    break

        result = await send_content_suggestion(webhook_url, item, team_member)
        if result.get("success"):
            sent += 1
        else:
            errors.append({"content_id": item.get("id"), "error": result.get("error")})

    return {"sent": sent, "total": len(queued), "errors": errors}
