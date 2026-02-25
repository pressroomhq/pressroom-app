"""Publisher — Post approved content directly via social OAuth tokens.

Pressroom owns the OAuth tokens per-org. No DreamFactory needed for publishing.
Each org connects their social accounts, and we post directly via platform APIs.

Per-channel publish actions (configured via publish_actions org setting):
  auto     — post directly via API (LinkedIn, Facebook, blog)
  slack    — send to Slack webhook for manual posting
  manual   — mark as published, user copies/pastes
  disabled — skip entirely
"""

import base64
import json
import logging
import re
from datetime import datetime
from services import social_auth
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

# Channels that support direct API publishing
DIRECT_CHANNELS = {"linkedin", "facebook", "blog", "devto"}

# Default publish action per channel
DEFAULT_PUBLISH_ACTIONS = {
    "linkedin": "auto",
    "facebook": "auto",
    "blog": "auto",
    "devto": "auto",
    "release_email": "auto",
    "newsletter": "auto",
    "yt_script": "auto",
}

CHANNEL_LABELS = {
    "linkedin": "LinkedIn",
    "facebook": "Facebook",
    "blog": "Blog",
    "devto": "Dev.to",
    "release_email": "Release Email",
    "newsletter": "Newsletter",
    "yt_script": "YouTube Script",
}


def get_publish_actions(settings: dict) -> dict:
    """Parse publish_actions from org settings, merging with defaults."""
    raw = settings.get("publish_actions", "{}")
    try:
        configured = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        configured = {}
    return {**DEFAULT_PUBLISH_ACTIONS, **configured}


async def publish_single(content: dict, settings: dict, dl: "DataLayer | None" = None) -> dict:
    """Post a single content item using stored OAuth tokens.

    If content.author is "team:N" and the team member has their own LinkedIn
    token, posts as them. Falls back to org-level token if not connected.
    """
    channel = content.get("channel", "")
    text = content.get("body", "")
    log.info("[publisher] Publishing to %s (content #%s, %d chars)...", channel, content.get("id"), len(text))

    if channel == "linkedin":
        token = settings.get("linkedin_access_token", "")
        author_urn = settings.get("linkedin_author_urn", "")

        # Try team member's personal token first
        content_author = content.get("author", "")
        if content_author.startswith("team:") and dl:
            try:
                member_id = int(content_author.split(":")[1])
                members = await dl.list_team_members()
                member = next((m for m in members if m["id"] == member_id), None)
                if member and member.get("linkedin_access_token") and member.get("linkedin_author_urn"):
                    token = member["linkedin_access_token"]
                    author_urn = member["linkedin_author_urn"]
                    log.info("Posting as team member %s (%s)", member.get("name"), author_urn)
            except Exception as e:
                log.warning("Could not resolve team member token: %s", e)

        if not token or not author_urn:
            return {"error": "LinkedIn not connected — authorize in Connections or connect your personal LinkedIn in Team"}
        return await social_auth.linkedin_post(token, author_urn, text)

    elif channel == "devto":
        log.info("[publisher] Posting to Dev.to as draft...")
        return await publish_to_devto(content, settings)

    elif channel == "facebook":
        page_token = settings.get("facebook_page_token", "")
        page_id = settings.get("facebook_page_id", "")
        if not page_token or not page_id:
            return {"error": "Facebook not connected — authorize in Connections"}
        return await social_auth.facebook_post(page_token, page_id, text)

    elif channel == "blog":
        log.info("[publisher] Publishing blog post via GitHub...")
        return await publish_blog_post(content, settings)

    else:
        log.info("[publisher] No direct publisher for channel '%s'", channel)
        return {"status": "no_destination", "note": f"No publisher for channel: {channel}"}


async def publish_to_devto(content: dict, settings: dict) -> dict:
    """Publish content to Dev.to as an unpublished draft via API key."""
    import httpx

    api_key = settings.get("devto_api_key", "")
    if not api_key:
        return {"error": "Dev.to not connected — add your API key in Connections"}

    headline = content.get("headline", "Untitled")
    body = content.get("body", "")

    clean_headline = re.sub(r'^(DEV\.TO|DEVTO|BLOG DRAFT|BLOG)\s*[:\-–—]?\s*(title\s*[:\-–—]?\s*)?', '', headline, flags=re.IGNORECASE).strip()
    # Also strip bare leading "title:" if it survived
    clean_headline = re.sub(r'^title\s*[:\-–—]\s*', '', clean_headline, flags=re.IGNORECASE).strip()
    body_with_credit = f"{body}\n\n---\n*Written with [Pressroom HQ](https://pressroomhq.com)*"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://dev.to/api/articles",
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "article": {
                        "title": clean_headline,
                        "body_markdown": body_with_credit,
                        "published": False,  # always draft first
                        "tags": ["webdev", "api", "opensource"],
                    }
                },
            )
            if resp.status_code == 401:
                return {"error": "Dev.to API key invalid — update it in Connections"}
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "devto_url": data.get("url", ""),
                "post_id": data.get("id", ""),
                "status": "draft",
            }
    except httpx.HTTPStatusError as e:
        log.error("Dev.to publish failed: %s — %s", e.response.status_code, e.response.text[:300])
        return {"error": f"Dev.to API error {e.response.status_code}"}
    except Exception as e:
        log.error("Dev.to publish failed: %s", e)
        return {"error": f"Dev.to publish failed: {e}"}


async def publish_blog_post(content: dict, settings: dict) -> dict:
    """Publish a blog post as a markdown file.

    If blog_publish_path is set, writes directly to disk (for local/self-hosted sites).
    Otherwise falls back to GitHub API publishing.
    """
    # Local file-write path (e.g. for our own Astro site on the same box)
    local_path = settings.get("blog_publish_path", "")
    if local_path:
        from services.blog_publisher import publish_to_blog
        path = publish_to_blog(content, local_path)
        if path:
            return {"success": True, "file": path}
        return {"error": f"Failed to write blog post to {local_path}"}

    import httpx

    gh_token = settings.get("github_token", "") or settings.get("blog_github_token", "")
    repo = settings.get("blog_github_repo", "")
    content_path = settings.get("blog_content_path", "src/content/blog")

    if not gh_token:
        return {"error": "No GitHub token configured — add one in Scout settings or Config → Company"}
    if not repo:
        return {"error": "No blog repo configured — set blog_github_repo in org settings (e.g. pressroomhq/pressroom-site)"}

    headline = content.get("headline", "Untitled")
    body = content.get("body", "")
    author = content.get("author_name", "")

    # Strip any leading channel prefix from headline
    clean_headline = re.sub(r'^(BLOG\s*DRAFT|BLOGDRAFT|BLOG)\s*[:\-–—]?\s*(title\s*[:\-–—]?\s*)?', '', headline, flags=re.IGNORECASE).strip()
    clean_headline = re.sub(r'^title\s*[:\-–—]\s*', '', clean_headline, flags=re.IGNORECASE).strip()

    # Build slug from headline
    slug = re.sub(r'[^a-z0-9]+', '-', clean_headline.lower()).strip('-')[:60]
    date_str = datetime.utcnow().strftime('%Y-%m-%d')
    filename = f"{date_str}-{slug}.md"
    file_path = f"{content_path.rstrip('/')}/{filename}"

    # Extract description — first non-empty line of body, truncated
    body_lines = [l.strip() for l in body.split('\n') if l.strip()]
    description = body_lines[0][:160] if body_lines else clean_headline

    # Build frontmatter + body
    md_content = f"""---
title: "{clean_headline.replace('"', "'")}"
description: "{description.replace('"', "'")}"
date: "{date_str}"
{f'author: "{author}"' if author else ''}
---

{body}
""".strip() + "\n"

    encoded = base64.b64encode(md_content.encode()).decode()

    headers = {
        "Authorization": f"Bearer {gh_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"https://api.github.com/repos/{repo}/contents/{file_path}",
            headers=headers,
            json={
                "message": f"blog: {clean_headline[:72]}",
                "content": encoded,
            },
            timeout=15,
        )

    if resp.status_code in (200, 201):
        data = resp.json()
        html_url = data.get("content", {}).get("html_url", "")
        return {"success": True, "url": html_url, "file": file_path}
    else:
        return {"error": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}


async def publish_approved(dl: DataLayer) -> list[dict]:
    """Publish all approved content according to per-channel action settings."""
    items = await dl.get_approved_unpublished()
    if not items:
        log.debug("[publisher] No approved unpublished content to publish")
        return []

    log.info("=" * 60)
    log.info("[publisher] PUBLISH APPROVED — %d items to publish", len(items))
    log.info("=" * 60)
    settings = await dl.get_all_settings()
    actions = get_publish_actions(settings)
    log.info("[publisher] Publish actions: %s", actions)
    webhook_url = settings.get("slack_webhook_url", "")

    results = []
    for content in items:
        channel = content.get("channel", "")
        content_id = content.get("id")
        action = actions.get(channel, "auto")
        log.info("[publisher] Processing #%s (%s) — action=%s", content_id, channel, action)

        # ── disabled: skip entirely ──
        if action == "disabled":
            log.info("[publisher] Skipping #%s — %s publishing disabled", content_id, channel)
            results.append({
                "id": content_id, "channel": channel,
                "result": {"status": "disabled"},
            })
            continue

        # ── slack: send to Slack for manual posting ──
        if action == "slack":
            if not webhook_url:
                results.append({
                    "id": content_id, "channel": channel,
                    "error": "Slack action configured but no webhook URL set",
                })
                continue
            try:
                from services.slack_notify import send_to_slack
                blocks = _build_publish_slack_blocks(content)
                slack_result = await send_to_slack(webhook_url, blocks)
                if slack_result.get("success"):
                    await dl.update_content_status(content_id, "published")
                    log.info("Sent %s content #%s to Slack", channel, content_id)
                results.append({"id": content_id, "channel": channel, "result": {
                    "status": "sent_to_slack", **slack_result,
                }})
            except Exception as e:
                log.error("Slack publish failed for %s #%s: %s", channel, content_id, e)
                results.append({"id": content_id, "channel": channel, "error": str(e)})
            continue

        # ── manual: mark published, user copies ──
        if action == "manual":
            await dl.update_content_status(content_id, "published")
            results.append({
                "id": content_id, "channel": channel,
                "result": {"status": "manual"},
            })
            continue

        # ── auto: publish via API if channel has a direct publisher ──
        if channel in DIRECT_CHANNELS:
            try:
                pub_result = await publish_single(content, settings, dl=dl)
                if pub_result.get("success"):
                    extra = {}
                    pid = pub_result.get("id") or pub_result.get("post_id") or ""
                    purl = pub_result.get("url") or pub_result.get("devto_url") or ""
                    if pid:
                        extra["post_id"] = str(pid)
                    if purl:
                        extra["post_url"] = str(purl)
                    await dl.update_content_status(content_id, "published", **extra)
                    log.info("Published %s content #%s (post_id=%s)", channel, content_id, pid)
                results.append({"id": content_id, "channel": channel, "result": pub_result})
            except Exception as e:
                log.error("Publish failed for %s #%s: %s", channel, content_id, e)
                results.append({"id": content_id, "channel": channel, "error": str(e)})
        else:
            # No direct publisher — mark published
            await dl.update_content_status(content_id, "published")
            results.append({
                "id": content_id, "channel": channel,
                "result": {"status": "no_destination"},
            })

    await dl.commit()
    published = sum(1 for r in results if r.get("result", {}).get("success") or r.get("result", {}).get("status") in ("manual", "sent_to_slack"))
    log.info("[publisher] PUBLISH APPROVED — complete: %d/%d items processed", published, len(items))
    return results


def _build_publish_slack_blocks(content: dict) -> list:
    """Build Slack Block Kit message for content ready to publish."""
    headline = content.get("headline", "Untitled")
    channel = content.get("channel", "unknown")
    body = content.get("body", "")
    content_id = content.get("id", "")

    label = CHANNEL_LABELS.get(channel, channel)

    # Short-form: show full body. Long-form: truncated preview.
    is_short = channel in ("linkedin", "facebook")
    body_display = body[:3000] if is_short else (body[:500] + ("..." if len(body) > 500 else ""))

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Ready to publish: {label}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Channel:*\n{label}"},
                {"type": "mrkdwn", "text": f"*Headline:*\n{headline[:100]}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{body_display}```"},
        },
        {"type": "divider"},
    ]

    if content_id:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Content #{content_id} — copy and post manually | Pressroom"},
            ],
        })

    return blocks
