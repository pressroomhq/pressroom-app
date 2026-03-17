"""Competitive Intelligence — audit competitors and compare against the org."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc

from api.auth import get_authenticated_data_layer
from models import CompetitorAudit
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/competitive", tags=["competitive"])


class ScanRequest(BaseModel):
    competitor_urls: list[str]


@router.post("/scan")
async def scan_competitors(req: ScanRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run SEO audit on each competitor, store results, return comparison."""
    from services.seo_audit import audit_domain

    results = []
    for url in req.competitor_urls[:5]:  # cap at 5
        domain = url.replace("https://", "").replace("http://", "").rstrip("/")
        try:
            audit = await audit_domain(domain)
            recs = audit.get("recommendations", {})
            score = recs.get("score", 0)
            analysis = recs.get("analysis", "")
            # Check for AI-related mentions in the audit
            has_ai = any(k in (analysis or "").lower()
                         for k in ["schema", "citation", "ai", "geo"])

            competitor = CompetitorAudit(
                org_id=dl.org_id,
                competitor_url=url,
                competitor_name=domain.split(".")[0].capitalize(),
                score=score,
                ai_citability=has_ai,
                result_json=json.dumps(audit, default=str)[:10000],
            )
            dl.db.add(competitor)
            results.append({
                "name": competitor.competitor_name,
                "url": url,
                "score": score,
                "ai_citability": has_ai,
                "top_issues": recs.get("critical", [])[:3],
            })
        except Exception as e:
            log.warning("Competitive scan failed for %s: %s", url, e)
            results.append({
                "name": domain.split(".")[0].capitalize(),
                "url": url,
                "score": 0,
                "ai_citability": False,
                "error": str(e),
            })

    await dl.db.commit()
    return {"competitors": results, "scanned_at": datetime.utcnow().isoformat()}


@router.get("/{org_id}")
async def get_competitive(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return latest competitive scan results for this org."""
    q = (
        select(CompetitorAudit)
        .where(CompetitorAudit.org_id == dl.org_id)
        .order_by(desc(CompetitorAudit.created_at))
        .limit(20)
    )
    rows = (await dl.db.execute(q)).scalars().all()

    # Group by competitor, take latest for each
    seen = {}
    for row in rows:
        if row.competitor_url not in seen:
            seen[row.competitor_url] = {
                "name": row.competitor_name,
                "url": row.competitor_url,
                "score": row.score,
                "ai_citability": row.ai_citability,
                "scanned_at": row.created_at.isoformat() if row.created_at else "",
            }

    return {"competitors": list(seen.values())}


@router.post("/suggest")
async def suggest_competitors(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate a list of competitor URLs for this org using Claude."""
    settings = await dl.get_all_settings()
    company_name = settings.get("onboard_company_name", "")
    domain = settings.get("onboard_domain", "")
    description = settings.get("onboard_description", "") or settings.get("company_description", "")

    if not company_name and not domain:
        return {"urls": []}

    try:
        import anthropic
        from config import settings as app_settings
        from services.token_tracker import log_token_usage
        key = app_settings.anthropic_api_key
        if not key:
            return {"urls": []}
        client = anthropic.AsyncAnthropic(api_key=key)
        context = f"Company: {company_name}\nDomain: {domain}"
        if description:
            context += f"\nDescription: {description[:400]}"

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system="""List exactly 4-5 competitor website URLs for this company.

Rules:
- Output only raw URLs, one per line (e.g. https://competitor.com)
- Real, existing companies that compete in the same market
- No explanation, no numbering, no bullets — just URLs""",
            messages=[{"role": "user", "content": context}],
        )
        await log_token_usage(dl.org_id, "competitive_suggest", response)
        lines = [l.strip() for l in response.content[0].text.strip().splitlines() if l.strip().startswith("http")]
        return {"urls": lines[:5]}
    except Exception as e:
        log.warning("Competitor suggestion failed: %s", e)
        return {"urls": []}
