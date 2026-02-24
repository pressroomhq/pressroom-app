"""Company Audit — holistic gap analysis of a company's digital presence."""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text

from config import settings
from database import get_data_layer
from services.data_layer import DataLayer
from services.token_tracker import log_token_usage

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/company", tags=["company"])


async def _gather_company_snapshot(dl: DataLayer) -> dict:
    """Collect everything we know about this company for audit."""
    all_settings = await dl.get_all_settings()
    assets = await dl.list_assets()
    blog_posts = []
    try:
        from models import BlogPost
        from sqlalchemy import select
        q = select(BlogPost).where(BlogPost.org_id == dl.org_id).order_by(BlogPost.published_at.desc()).limit(20)
        result = await dl.db.execute(q)
        blog_posts = [{"title": p.title, "url": p.url, "published_at": p.published_at.isoformat() if p.published_at else None} for p in result.scalars().all()]
    except Exception:
        pass

    # Content stats
    content_stats = {}
    try:
        org_filter = "AND org_id = :org_id" if dl.org_id else ""
        params = {"org_id": dl.org_id} if dl.org_id else {}
        row = (await dl.db.execute(text(f"SELECT COUNT(*) as total FROM content WHERE 1=1 {org_filter}"), params)).first()
        content_stats["total"] = row.total if row else 0
        rows = (await dl.db.execute(text(f"SELECT channel, COUNT(*) as cnt FROM content WHERE 1=1 {org_filter} GROUP BY channel"), params)).fetchall()
        content_stats["by_channel"] = {r.channel: r.cnt for r in rows}
        rows = (await dl.db.execute(text(f"SELECT status, COUNT(*) as cnt FROM content WHERE 1=1 {org_filter} GROUP BY status"), params)).fetchall()
        content_stats["by_status"] = {r.status: r.cnt for r in rows}
    except Exception:
        pass

    # Signal stats
    signal_count = 0
    try:
        row = (await dl.db.execute(text(f"SELECT COUNT(*) as total FROM signals WHERE 1=1 {org_filter}"), params)).first()
        signal_count = row.total if row else 0
    except Exception:
        pass

    # Team members
    team = []
    try:
        from models import TeamMember
        from sqlalchemy import select as sel
        q = sel(TeamMember).where(TeamMember.org_id == dl.org_id)
        result = await dl.db.execute(q)
        team = [{"name": m.name, "title": m.title} for m in result.scalars().all()]
    except Exception:
        pass

    # Categorize assets
    asset_types = {}
    for a in assets:
        t = a.get("asset_type", "unknown")
        asset_types.setdefault(t, []).append(a)

    return {
        "company_name": all_settings.get("onboard_company_name", ""),
        "domain": all_settings.get("onboard_domain", ""),
        "industry": all_settings.get("onboard_industry", ""),
        "topics": all_settings.get("onboard_topics", "[]"),
        "competitors": all_settings.get("onboard_competitors", "[]"),
        "golden_anchor": all_settings.get("golden_anchor", ""),
        "voice_persona": all_settings.get("voice_persona", ""),
        "social_profiles": all_settings.get("social_profiles", "{}"),
        "company_properties": all_settings.get("company_properties", "{}"),
        "assets": {t: [{"url": a["url"], "label": a.get("label", "")} for a in items] for t, items in asset_types.items()},
        "asset_count": len(assets),
        "blog_posts": blog_posts,
        "blog_post_count": len(blog_posts),
        "content_stats": content_stats,
        "signal_count": signal_count,
        "team_members": team,
        "scout_sources": {
            "github_orgs": all_settings.get("scout_github_orgs", "[]"),
            "github_repos": all_settings.get("scout_github_repos", "[]"),
            "hn_keywords": all_settings.get("scout_hn_keywords", "[]"),
            "subreddits": all_settings.get("scout_subreddits", "[]"),
            "rss_feeds": all_settings.get("scout_rss_feeds", "[]"),
            "web_queries": all_settings.get("scout_web_queries", "[]"),
        },
        "has_linkedin": bool(all_settings.get("linkedin_access_token", "")),
        "has_hubspot": bool(all_settings.get("hubspot_access_token", "")),
    }


@router.post("/audit")
async def run_company_audit(dl: DataLayer = Depends(get_data_layer)):
    """Run a holistic audit of the company's digital presence and marketing readiness."""
    import anthropic

    snapshot = await _gather_company_snapshot(dl)
    api_key = await dl.get_setting("anthropic_api_key") or settings.anthropic_api_key
    if not api_key:
        return {"error": "No Anthropic API key configured"}

    prompt = f"""You are a senior marketing strategist auditing a company's digital presence. Analyze this company snapshot and identify the most impactful gaps, problems, and opportunities.

COMPANY SNAPSHOT:
{json.dumps(snapshot, indent=2, default=str)}

Produce a JSON array of findings. Each finding should have:
- "severity": "critical" | "warning" | "opportunity"
- "category": "presence" | "content" | "seo" | "social" | "technical" | "strategy"
- "title": short headline (under 60 chars)
- "detail": 1-2 sentence explanation of why this matters and what to do
- "metric": optional supporting number or fact (null if not applicable)

Focus on:
1. Missing digital properties — check company_properties for empty values (no docs, no support page, no pricing, no careers page, no changelog, no status page, no newsletter). Each empty property is a gap worth flagging.
2. Missing social accounts — check social_profiles for empty values (no LinkedIn, no YouTube, no blog URL, etc.)
3. Content gaps (no video content, only one channel, no email/newsletter)
4. Stale or thin content (old blog posts, few signals, low content volume)
5. SEO red flags (no documented domain, missing key assets)
6. Brand/voice gaps (no golden anchor, no persona defined, no competitors mapped)
7. Signal monitoring gaps (few scout sources, missing major platforms)
8. Integration gaps (no LinkedIn connected, no HubSpot, no publishing pipeline)
9. Team gaps (no team members, missing bios/expertise)

Be specific and actionable. Prioritize the 8-15 most impactful findings.
Return ONLY the JSON array, no markdown wrapping."""

    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=settings.claude_model_fast,
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "["},
            ],
        )
        await log_token_usage(dl.org_id, "company_audit", response)
        raw = "[" + response.content[0].text.strip()
        findings = json.loads(raw)
        log.info("COMPANY AUDIT — %d findings for %s", len(findings), snapshot.get("company_name", "unknown"))
        return {"findings": findings, "company": snapshot.get("company_name", ""), "audited_at": datetime.utcnow().isoformat()}
    except json.JSONDecodeError:
        return {"findings": [], "error": "Failed to parse audit results", "raw": raw[:500]}
    except Exception as e:
        log.error("COMPANY AUDIT failed: %s", e)
        return {"error": str(e)}
