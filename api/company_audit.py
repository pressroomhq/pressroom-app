"""Company Audit — holistic gap analysis of a company's digital presence."""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text

from config import settings
from api.auth import get_authenticated_data_layer
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


def _rule_based_findings(snapshot: dict) -> list[dict]:
    """Deterministic checks — always run regardless of LLM output.

    These fire based on hard facts in the snapshot: missing fields,
    zero counts, disconnected integrations. No hallucination possible.
    """
    findings = []

    def add(severity, category, title, detail, metric=None):
        findings.append({"severity": severity, "category": category,
                         "title": title, "detail": detail, "metric": metric})

    social = {}
    try:
        social = json.loads(snapshot.get("social_profiles", "{}") or "{}")
    except Exception:
        pass

    props = {}
    try:
        props = json.loads(snapshot.get("company_properties", "{}") or "{}")
    except Exception:
        pass

    scout = snapshot.get("scout_sources", {})

    # ── Brand / voice ──
    if not snapshot.get("golden_anchor"):
        add("critical", "strategy", "No Golden Anchor defined",
            "Your north star message is missing. Every content piece lacks a unifying thread.")
    if not snapshot.get("voice_persona"):
        add("critical", "strategy", "No voice persona configured",
            "Pressroom can't generate on-brand content without a defined persona.")

    competitors = []
    try:
        competitors = json.loads(snapshot.get("competitors", "[]") or "[]")
    except Exception:
        pass
    if not competitors:
        add("warning", "strategy", "No competitors mapped",
            "Competitive context is missing — content positioning will be generic.")

    # ── Social presence ──
    if not social.get("linkedin"):
        add("critical", "social", "No LinkedIn profile detected",
            "LinkedIn is the highest-ROI B2B content channel. Add your company page URL.")
    if not social.get("youtube"):
        add("warning", "social", "No YouTube channel detected",
            "Video is the fastest-growing B2B content format. Even repurposed clips compound.")
    if not social.get("github") and snapshot.get("industry", "").lower() in ("", "software", "saas", "developer tools", "api", "tech"):
        add("warning", "social", "No GitHub presence detected",
            "For a technical company, GitHub is a distribution channel, not just a repo host.")

    # ── Digital properties ──
    if not props.get("docs"):
        add("warning", "presence", "No documentation site found",
            "Docs are high-intent SEO pages. If you have them, add the URL to your company properties.")
    if not props.get("pricing"):
        add("warning", "presence", "No pricing page detected",
            "Pricing pages are among the highest-converting pages on any B2B site.")
    if not props.get("changelog"):
        add("opportunity", "content", "No changelog or releases page",
            "Changelogs are low-effort, high-trust content — each release is a story.")

    # ── Content ──
    content_total = snapshot.get("content_stats", {}).get("total", 0)
    if content_total == 0:
        add("critical", "content", "Zero content published",
            "No content has been generated yet. Run your first piece from the Desk.")
    elif content_total < 5:
        add("warning", "content", "Very thin content library",
            f"Only {content_total} pieces published. Aim for consistent weekly output.", content_total)

    blog_count = snapshot.get("blog_post_count", 0)
    if blog_count == 0:
        add("warning", "content", "No blog posts scraped",
            "Blog post history helps Pressroom match your publishing style and cadence.")

    # ── Team ──
    team = snapshot.get("team_members", [])
    if not team:
        add("warning", "strategy", "No team members added",
            "Team members unlock byline content, LinkedIn ghostwriting, and expertise targeting.")

    # ── Integrations ──
    if not snapshot.get("has_linkedin"):
        add("warning", "technical", "LinkedIn not connected",
            "Connect LinkedIn in Settings to enable one-click publishing from Pressroom.")
    if not snapshot.get("has_hubspot"):
        add("opportunity", "technical", "HubSpot not connected",
            "HubSpot integration unlocks contact-aware content and pipeline attribution.")

    # ── Signal monitoring ──
    hn_keywords = []
    try:
        hn_keywords = json.loads(scout.get("hn_keywords", "[]") or "[]")
    except Exception:
        pass
    subreddits = []
    try:
        subreddits = json.loads(scout.get("subreddits", "[]") or "[]")
    except Exception:
        pass
    if not hn_keywords and not subreddits:
        add("warning", "technical", "No signal sources configured",
            "Scout has no sources to monitor. Set up subreddits and HN keywords for your industry.")

    return findings


@router.get("/audit")
@router.post("/audit")
async def run_company_audit(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run a holistic audit of the company's digital presence and marketing readiness."""
    import anthropic

    snapshot = await _gather_company_snapshot(dl)
    api_key = await dl.get_setting("anthropic_api_key") or settings.anthropic_api_key

    # Always run rule-based checks first — these are guaranteed findings
    rule_findings = _rule_based_findings(snapshot)

    if not api_key:
        # No API key — just return rule-based findings
        return {"findings": rule_findings, "company": snapshot.get("company_name", ""),
                "audited_at": datetime.utcnow().isoformat(), "source": "rules"}

    # Ask Claude for additional strategic findings
    prompt = f"""You are a senior marketing strategist auditing a company's digital presence.

COMPANY SNAPSHOT:
{json.dumps(snapshot, indent=2, default=str)}

The following gaps have already been flagged by automated checks (do NOT repeat these):
{json.dumps([f["title"] for f in rule_findings], indent=2)}

Find ADDITIONAL strategic findings these automated checks may have missed. Look for:
- Positioning weaknesses specific to this company and industry
- Content strategy gaps relative to their competitors
- Audience targeting problems
- Messaging inconsistencies from the crawled pages
- Channel mix imbalances for their specific market
- Opportunities their competitors are exploiting that they're missing

Each finding must have:
- "severity": "critical" | "warning" | "opportunity"
- "category": "presence" | "content" | "seo" | "social" | "technical" | "strategy"
- "title": short headline (under 60 chars)
- "detail": 1-2 sentence explanation of why this matters and what to do
- "metric": optional supporting number or fact (null if not applicable)

Return 4-8 findings. Be specific to THIS company — no generic advice.
Return ONLY the JSON array."""

    client = anthropic.AsyncAnthropic(api_key=api_key)
    llm_findings = []
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
        llm_findings = json.loads(raw)
    except Exception as e:
        log.warning("COMPANY AUDIT LLM failed (rule findings still returned): %s", e)

    # Merge: rule-based first (deterministic), then LLM additions
    all_findings = rule_findings + llm_findings
    log.info("COMPANY AUDIT — %d findings (%d rules + %d llm) for %s",
             len(all_findings), len(rule_findings), len(llm_findings),
             snapshot.get("company_name", "unknown"))

    return {"findings": all_findings, "company": snapshot.get("company_name", ""),
            "audited_at": datetime.utcnow().isoformat(), "source": "hybrid"}
