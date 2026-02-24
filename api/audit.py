"""Audit endpoints — SEO site audits and GitHub README audits, with persistence."""

import json
import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from database import get_data_layer
from services.data_layer import DataLayer
from services.seo_audit import audit_domain
from services.readme_audit import audit_readme

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditRequest(BaseModel):
    domain: str = ""  # if empty, uses the org's onboarded domain
    max_pages: int = 15


class ReadmeAuditRequest(BaseModel):
    repo: str = ""  # owner/repo or full GitHub URL


class ReadmeFixRequest(BaseModel):
    repo_url: str          # full GitHub URL for cloning
    base_branch: str = "main"
    audit_id: int | None = None   # optional — loads recommendations from saved audit
    recommendations: str = ""     # or pass recommendations directly


@router.post("/seo")
async def run_seo_audit(req: AuditRequest, deep: bool = Query(True), dl: DataLayer = Depends(get_data_layer)):
    """Run an SEO audit on the org's domain (or a specified domain). Saves result.

    Set ?deep=false for fast mode (basic checks only, no Claude analysis).
    """
    domain = req.domain

    if not domain:
        settings = await dl.get_all_settings()
        domain = settings.get("onboard_domain", "")

        if not domain:
            if dl.org_id:
                org = await dl.get_org(dl.org_id)
                domain = org.get("domain", "") if org else ""

    if not domain:
        return {"error": "No domain specified and no org domain found. Pass a domain in the request."}

    api_key = await dl.resolve_api_key()

    # Use skill-based audit for deep mode
    if deep and api_key:
        try:
            from skills.seo_geo import run as seo_geo_run
            skill_result = await seo_geo_run(domain, context={"deep": True})
            if "error" not in skill_result:
                saved = await dl.save_audit({
                    "audit_type": "seo",
                    "target": skill_result.get("url", domain),
                    "score": skill_result.get("score", 0),
                    "total_issues": len(skill_result.get("recommendations", [])),
                    "result": skill_result,
                })
                await dl.commit()
                skill_result["audit_id"] = saved["id"]
                return skill_result
        except Exception:
            pass  # fall through to default audit

    result = await audit_domain(domain, max_pages=req.max_pages, api_key=api_key)

    if "error" not in result:
        saved = await dl.save_audit({
            "audit_type": "seo",
            "target": result.get("domain", domain),
            "score": result.get("recommendations", {}).get("score", 0),
            "total_issues": result.get("recommendations", {}).get("total_issues", 0),
            "result": result,
        })
        await dl.commit()
        result["audit_id"] = saved["id"]

    return result


@router.post("/readme")
async def run_readme_audit(req: ReadmeAuditRequest, dl: DataLayer = Depends(get_data_layer)):
    """Run a README quality audit on a GitHub repo. Saves result."""
    repo = req.repo

    if not repo:
        return {"error": "No repo specified. Pass a repo like 'owner/repo' or a GitHub URL."}

    api_key = await dl.resolve_api_key()
    result = await audit_readme(repo, api_key=api_key)

    if "error" not in result:
        saved = await dl.save_audit({
            "audit_type": "readme",
            "target": result.get("repo", repo),
            "score": result.get("recommendations", {}).get("score", 0),
            "total_issues": result.get("recommendations", {}).get("total_issues", 0),
            "result": result,
        })
        await dl.commit()
        result["audit_id"] = saved["id"]

    return result


@router.get("/history")
async def list_audits(
    audit_type: str | None = Query(None),
    limit: int = Query(20),
    dl: DataLayer = Depends(get_data_layer),
):
    """List saved audit results for this org."""
    return await dl.list_audits(audit_type=audit_type, limit=limit)


@router.get("/history/{audit_id}")
async def get_audit(audit_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Get a single saved audit result with full data."""
    result = await dl.get_audit(audit_id)
    if not result:
        return {"error": "Audit not found"}
    return result


@router.delete("/history/{audit_id}")
async def delete_audit(audit_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Delete a saved audit result."""
    deleted = await dl.delete_audit(audit_id)
    await dl.commit()
    if not deleted:
        return {"error": "Audit not found"}
    return {"deleted": audit_id}


class ScanAllRequest(BaseModel):
    deep: bool = True


@router.post("/scan-all")
async def scan_all_orgs(req: ScanAllRequest):
    """Run SEO+GEO audit on every org that has a domain configured. Saves each result."""
    from database import async_session
    from sqlalchemy import select
    from models import Organization, AuditResult

    results = []

    async with async_session() as session:
        orgs_res = await session.execute(select(Organization))
        orgs = orgs_res.scalars().all()

    for org in orgs:
        domain = org.domain
        if not domain:
            results.append({
                "org_id": org.id,
                "org_name": org.name,
                "domain": None,
                "score": None,
                "status": "skipped",
                "error": "No domain configured",
            })
            continue

        try:
            from skills.seo_geo import run as seo_geo_run
            skill_result = await seo_geo_run(domain, context={"deep": req.deep})

            if "error" in skill_result:
                raise ValueError(skill_result["error"])

            async with async_session() as session:
                audit = AuditResult(
                    org_id=org.id,
                    audit_type="seo",
                    target=skill_result.get("url", domain),
                    score=skill_result.get("score", 0),
                    total_issues=len(skill_result.get("recommendations", [])),
                    result_json=json.dumps(skill_result),
                    created_at=datetime.datetime.utcnow(),
                )
                session.add(audit)
                await session.commit()
                saved_id = audit.id

            results.append({
                "org_id": org.id,
                "org_name": org.name,
                "domain": domain,
                "score": skill_result.get("score", 0),
                "status": "ok",
                "audit_id": saved_id,
            })

        except Exception as e:
            results.append({
                "org_id": org.id,
                "org_name": org.name,
                "domain": domain,
                "score": None,
                "status": "error",
                "error": str(e),
            })

    return {"scanned": len(results), "results": results}


@router.get("/history/{audit_id}/export")
async def export_audit(audit_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Export a saved audit as a standalone downloadable HTML report."""
    audit = await dl.get_audit(audit_id)
    if not audit:
        return {"error": "Audit not found"}

    result = audit.get("result", {})
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except Exception:
            result = {}

    score = audit.get("score", result.get("score", 0))
    target = audit.get("target", "")
    audit_date = audit.get("created_at", "")
    recommendations = result.get("recommendations", [])
    p0 = [r for r in recommendations if r.get("priority") == "P0"]
    p1 = [r for r in recommendations if r.get("priority") == "P1"]
    p2 = [r for r in recommendations if r.get("priority") == "P2"]
    robots = result.get("robots", {})
    geo = result.get("geo", {})
    meta = result.get("meta", {})
    schema = result.get("schema", {})

    score_color = "#22cc44" if score >= 80 else "#ffb000" if score >= 60 else "#cc3333"

    def rec_rows(recs):
        if not recs:
            return '<tr><td colspan="2" style="color:#555;padding:8px 0;">None found.</td></tr>'
        rows = ""
        for r in recs:
            cat = r.get("category", "").upper()
            action = r.get("action", "")
            rows += (
                f'<tr><td style="color:#888;font-size:11px;padding:6px 12px 6px 0;'
                f'white-space:nowrap;">[{cat}]</td>'
                f'<td style="padding:6px 0;">{action}</td></tr>'
            )
        return rows

    blocked = robots.get("blocked_bots", [])
    blocked_section = ""
    if blocked:
        blocked_section = (
            f'<div class="section"><h2>AI BOT ACCESS — WARNING</h2>'
            f'<div style="color:#cc3333;">Blocked in robots.txt: {", ".join(blocked)}</div>'
            f'<div style="color:#888;margin-top:8px;font-size:12px;">'
            f'These platforms will not index or cite this site until unblocked.</div></div>'
        )

    geo_section = ""
    if geo.get("analysis"):
        geo_section = (
            f'<div class="section"><h2>GEO ANALYSIS — AI CITATION READINESS</h2>'
            f'<div class="analysis">{geo["analysis"]}</div></div>'
        )

    meta_section = ""
    if meta.get("recommendations"):
        meta_section = (
            f'<div class="section"><h2>RECOMMENDED META TAGS</h2>'
            f'<div class="analysis">{meta["recommendations"]}</div></div>'
        )

    schema_section = ""
    if schema.get("markup"):
        schema_section = (
            f'<div class="section"><h2>SCHEMA MARKUP (JSON-LD)</h2>'
            f'<div class="schema">{schema["markup"]}</div></div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEO + GEO Audit — {target}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#0a0a0a;color:#c8c8c8;font-family:'IBM Plex Mono','Courier New',monospace;font-size:13px;line-height:1.6;padding:40px;}}
.header{{border-bottom:1px solid #333;padding-bottom:24px;margin-bottom:32px;}}
.brand{{color:#ffb000;font-size:11px;letter-spacing:0.15em;margin-bottom:8px;}}
h1{{color:#ffb000;font-size:20px;font-weight:600;margin-bottom:4px;}}
.meta{{color:#555;font-size:11px;}}
.score-block{{display:inline-block;margin:24px 0;}}
.score-num{{font-size:64px;font-weight:700;color:{score_color};line-height:1;}}
.score-label{{font-size:11px;color:#555;letter-spacing:0.1em;margin-top:4px;}}
h2{{color:#ffb000;font-size:12px;letter-spacing:0.1em;margin:32px 0 12px;border-bottom:1px solid #222;padding-bottom:6px;}}
table{{width:100%;border-collapse:collapse;}}
.section{{margin-bottom:40px;}}
.analysis{{color:#c8c8c8;white-space:pre-wrap;background:#111;padding:16px;border-left:2px solid #333;font-size:12px;}}
.schema{{color:#888;white-space:pre-wrap;background:#111;padding:16px;font-size:11px;}}
.footer{{border-top:1px solid #222;padding-top:24px;margin-top:48px;color:#333;font-size:11px;}}
.footer a{{color:#555;}}
</style>
</head>
<body>
<div class="header">
  <div class="brand">PRESSROOM HQ — SEO + GEO AUDIT REPORT</div>
  <h1>{target}</h1>
  <div class="meta">Audited: {audit_date} &nbsp;|&nbsp; Generated by Pressroom HQ</div>
</div>
<div class="score-block">
  <div class="score-num">{score}</div>
  <div class="score-label">OVERALL SCORE / 100</div>
</div>
<div class="section">
  <h2>P0 — CRITICAL (Fix Immediately)</h2>
  <table>{rec_rows(p0)}</table>
</div>
<div class="section">
  <h2>P1 — IMPORTANT</h2>
  <table>{rec_rows(p1)}</table>
</div>
<div class="section">
  <h2>P2 — INCREMENTAL</h2>
  <table>{rec_rows(p2)}</table>
</div>
{blocked_section}
{geo_section}
{meta_section}
{schema_section}
<div class="footer">
  Report generated by <a href="https://pressroomhq.com">Pressroom HQ</a> — AI-powered digital presence for portfolio companies.
</div>
</body>
</html>"""

    filename = (
        target.replace("https://", "").replace("http://", "")
        .replace("/", "-").strip("-")
    )
    filename = f"pressroom-audit-{filename}.html"

    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/readme/fix")
async def fix_readme_with_pr(req: ReadmeFixRequest, dl: DataLayer = Depends(get_data_layer)):
    """Improve a repo's README based on audit recommendations and create a PR."""
    from services.seo_pipeline import fix_readme_with_pr as _fix

    if not req.repo_url:
        return {"error": "repo_url is required."}

    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured. Add one in Account settings."}

    # Get recommendations — from audit_id or directly
    recommendations = req.recommendations
    if not recommendations and req.audit_id:
        audit = await dl.get_audit(req.audit_id)
        if audit and audit.get("result"):
            recs = audit["result"].get("recommendations", {})
            recommendations = recs.get("analysis", "")

    if not recommendations:
        return {"error": "No recommendations provided. Run a README audit first."}

    result = await _fix(
        repo_url=req.repo_url,
        base_branch=req.base_branch,
        audit_recommendations=recommendations,
        api_key=api_key,
    )

    return result
