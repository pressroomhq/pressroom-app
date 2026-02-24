"""Team Scraper — extract team members from company About/Team pages using Claude."""

import json
import logging
import re

import anthropic

from config import settings
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

MAX_MEMBERS = 20


def _get_client(api_key: str | None = None):
    """Lazy client — uses explicit key if provided, else runtime config."""
    return anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)


def _repair_json(text: str) -> list | None:
    """Try to parse JSON array from Claude's response."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text.strip())

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "members" in result:
            return result["members"]
        if isinstance(result, dict) and "team_members" in result:
            return result["team_members"]
        return None
    except (json.JSONDecodeError, ValueError):
        pass

    # Find outermost [ ... ]
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _extract_text(html: str) -> str:
    """Rough text extraction from HTML — strip tags, collapse whitespace."""
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


async def extract_team_members(html: str, page_url: str,
                                api_key: str | None = None) -> list[dict]:
    """Extract team member info from an About/Team page using Claude.

    Returns a list of dicts with: name, title, bio, photo_url, linkedin_url,
    email, expertise_tags.
    """
    # Extract text and keep it manageable
    page_text = _extract_text(html)
    if len(page_text) < 30:
        return []

    # Also extract image URLs and LinkedIn URLs from raw HTML for Claude's reference
    img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    linkedin_urls = re.findall(r'https?://(?:www\.)?linkedin\.com/in/[^\s"\'<>]+', html, re.IGNORECASE)

    extra_context = ""
    if img_urls:
        extra_context += f"\nImage URLs found on page (may be team photos): {img_urls[:30]}\n"
    if linkedin_urls:
        extra_context += f"\nLinkedIn profile URLs found: {linkedin_urls[:20]}\n"

    prompt = f"""Extract team members from this company page.

Page URL: {page_url}

PAGE CONTENT:
{page_text[:8000]}
{extra_context}

Return a JSON array of team members. For each person found, include:
- name: full name (required)
- title: job title or role
- bio: brief bio or description (keep to 2-3 sentences max)
- photo_url: URL to their photo if visible in the image URLs above
- linkedin_url: their LinkedIn profile URL if found
- email: their email if mentioned
- expertise_tags: array of 2-5 inferred expertise areas based on their title and bio (e.g. ["engineering", "cloud infrastructure", "DevOps"])

Rules:
- Only include actual people, not company names or departments
- Maximum {MAX_MEMBERS} members
- If you can't find any team members, return an empty array []
- Infer expertise_tags from the person's title and bio — be specific, not generic
- Return ONLY the JSON array, no markdown fences or commentary"""

    try:
        response = _get_client(api_key).messages.create(
            model=settings.claude_model_fast,
            max_tokens=4000,
            system="You extract structured team member data from company web pages. Return valid JSON arrays only.",
            messages=[{"role": "user", "content": prompt}],
        )

        await log_token_usage(None, "team_scraper", response)
        text = response.content[0].text
        log.info("TEAM EXTRACT RAW (%d chars): %s", len(text), text[:500])

        members = _repair_json(text)
        if members is None:
            log.error("TEAM EXTRACT JSON PARSE FAILED.\nRAW: %s", text[:1000])
            return []

        # Normalize and cap
        result = []
        for m in members[:MAX_MEMBERS]:
            if not isinstance(m, dict) or not m.get("name"):
                continue
            tags = m.get("expertise_tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, ValueError):
                    tags = [t.strip() for t in tags.split(",") if t.strip()]
            result.append({
                "name": str(m.get("name", "")).strip(),
                "title": str(m.get("title", "")).strip(),
                "bio": str(m.get("bio", "")).strip(),
                "photo_url": str(m.get("photo_url", "")).strip(),
                "linkedin_url": str(m.get("linkedin_url", "")).strip(),
                "email": str(m.get("email", "")).strip(),
                "expertise_tags": tags if isinstance(tags, list) else [],
            })

        log.info("TEAM EXTRACT — found %d members from %s", len(result), page_url)
        return result

    except Exception as e:
        log.error("TEAM EXTRACT ERROR — %s", str(e))
        return []
