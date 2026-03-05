"""Audit endpoints — SEO site audits and GitHub README audits, with persistence."""

import json
import datetime
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.seo_audit import audit_domain
from services.readme_audit import audit_readme

log = logging.getLogger("pressroom.audit")

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


class ActionItemStatusUpdate(BaseModel):
    status: str  # open, in_progress, resolved


@router.post("/seo")
async def run_seo_audit(req: AuditRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run a deep SEO audit on the org's domain (or a specified domain). Saves result + action items."""
    domain = req.domain

    if not domain:
        org_settings = await dl.get_all_settings()
        domain = org_settings.get("onboard_domain", "")

        if not domain and dl.org_id:
            org = await dl.get_org(dl.org_id)
            domain = org.get("domain", "") if org else ""

    if not domain:
        return {"error": "No domain specified and no org domain found. Pass a domain in the request."}

    api_key = await dl.resolve_api_key()
    result = await audit_domain(domain, max_pages=req.max_pages, api_key=api_key)

    if "error" not in result:
        saved = await dl.save_audit({
            "audit_type": "seo",
            "target": result.get("domain", domain),
            "score": result.get("recommendations", {}).get("score", 0),
            "total_issues": result.get("recommendations", {}).get("total_issues", 0),
            "result": result,
        })
        # save_audit already flushes so saved["id"] is available

        # Persist action items
        action_items = result.get("action_items", [])
        if action_items:
            await dl.upsert_action_items(saved["id"], action_items)

        await dl.commit()
        result["audit_id"] = saved["id"]
        result["action_items_saved"] = len(action_items)

    return result


@router.get("/action-items")
async def list_action_items(
    status: str | None = Query(None),
    limit: int = Query(100),
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """List persisted action items for this org."""
    return await dl.list_action_items(status=status, limit=limit)


@router.patch("/action-items/{item_id}")
async def update_action_item(item_id: int, req: ActionItemStatusUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update status of an action item (open, in_progress, resolved)."""
    valid = {"open", "in_progress", "resolved"}
    if req.status not in valid:
        return {"error": f"Invalid status. Must be one of: {', '.join(valid)}"}
    updated = await dl.update_action_item_status(item_id, req.status)
    if not updated:
        return {"error": "Action item not found"}
    await dl.commit()
    return updated


@router.post("/readme")
async def run_readme_audit(req: ReadmeAuditRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
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
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """List saved audit results for this org."""
    return await dl.list_audits(audit_type=audit_type, limit=limit)


@router.get("/history/{audit_id}")
async def get_audit(audit_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get a single saved audit result with full data."""
    result = await dl.get_audit(audit_id)
    if not result:
        return {"error": "Audit not found"}
    return result


@router.delete("/history/{audit_id}")
async def delete_audit(audit_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Delete a saved audit result."""
    deleted = await dl.delete_audit(audit_id)
    await dl.commit()
    if not deleted:
        return {"error": "Audit not found"}
    return {"deleted": audit_id}


class ScanAllRequest(BaseModel):
    max_pages: int = 5  # lighter than UI deep scan (15) for batch speed


@router.post("/scan-all")
async def scan_all_orgs(req: ScanAllRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run SEO audit on every org that has a domain. Uses the SAME engine as the UI deep scan."""
    from database import async_session, get_data_layer_for_org
    from sqlalchemy import select
    from models import Organization

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
            org_dl = await get_data_layer_for_org(org.id)
            api_key = await org_dl.resolve_api_key()

            # Same engine as POST /audit/seo — deterministic, no Claude
            result = await audit_domain(domain, max_pages=req.max_pages, api_key=api_key)

            if "error" in result:
                raise ValueError(result["error"])

            # Save in exactly the same format as POST /audit/seo
            saved = await org_dl.save_audit({
                "audit_type": "seo",
                "target": result.get("domain", domain),
                "score": result.get("recommendations", {}).get("score", 0),
                "total_issues": result.get("recommendations", {}).get("total_issues", 0),
                "result": result,
            })

            action_items = result.get("action_items", [])
            if action_items:
                await org_dl.upsert_action_items(saved["id"], action_items)

            await org_dl.commit()

            results.append({
                "org_id": org.id,
                "org_name": org.name,
                "domain": domain,
                "score": result.get("recommendations", {}).get("score", 0),
                "status": "ok",
                "audit_id": saved["id"],
            })

        except Exception as e:
            log.exception("scan-all failed for org %s (%s)", org.id, domain)
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
async def export_audit(audit_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
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
async def fix_readme_with_pr(req: ReadmeFixRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
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


# ──────────────────────────────────────
# Generate missing files (llms.txt, robots.txt, sitemap.xml)
# ──────────────────────────────────────

GENERATABLE_FILES = {"llms_txt", "robots_txt", "sitemap_xml"}

FILE_LABELS = {
    "llms_txt": "llms.txt",
    "robots_txt": "robots.txt",
    "sitemap_xml": "sitemap.xml",
}


class GenerateFileRequest(BaseModel):
    file_type: str  # llms_txt, robots_txt, sitemap_xml
    action_item_id: int | None = None


@router.post("/generate-file")
async def generate_file(req: GenerateFileRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate a missing file (llms.txt, robots.txt, sitemap.xml) using org context + Claude."""
    if req.file_type not in GENERATABLE_FILES:
        return {"error": f"Unsupported file type. Must be one of: {', '.join(GENERATABLE_FILES)}"}

    # Gather org context
    org = await dl.get_org(dl.org_id) if dl.org_id else None
    settings = await dl.get_all_settings()
    assets = await dl.list_assets()
    blog_posts = await dl.list_blog_posts(limit=100)

    domain = settings.get("onboard_domain", "")
    if not domain and org:
        domain = org.get("domain", "")
    if not domain:
        return {"error": "No domain configured. Run onboarding first or set a domain in settings."}

    # Ensure https prefix
    if not domain.startswith("http"):
        domain = f"https://{domain}"

    company_name = settings.get("company_name", org.get("name", "") if org else "")
    description = settings.get("company_description", "")
    topics = settings.get("topics", "")

    # Collect page URLs from assets and blog posts
    site_urls = []
    for a in assets:
        if a.get("url") and a.get("asset_type") in ("subdomain", "blog", "docs", "product", "page"):
            site_urls.append({"url": a["url"], "label": a.get("label", a.get("asset_type", ""))})
    for bp in blog_posts:
        if bp.get("url"):
            site_urls.append({"url": bp["url"], "label": bp.get("title", "blog post")})

    # Build the prompt
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured. Add one in Account settings."}

    file_label = FILE_LABELS[req.file_type]
    prompt = _build_generate_prompt(req.file_type, domain, company_name, description, topics, site_urls)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            content = "\n".join(lines)

        log.info("Generated %s for org %s (%d chars)", file_label, dl.org_id, len(content))

        # If we have an action_item_id, mark it in_progress
        if req.action_item_id:
            await dl.update_action_item_status(req.action_item_id, "in_progress")
            await dl.commit()

        return {
            "file_type": req.file_type,
            "filename": file_label,
            "content": content,
            "domain": domain,
            "action_item_id": req.action_item_id,
        }

    except Exception as e:
        log.exception("Failed to generate %s", file_label)
        return {"error": f"Generation failed: {str(e)}"}


def _build_generate_prompt(
    file_type: str,
    domain: str,
    company_name: str,
    description: str,
    topics: str,
    site_urls: list[dict],
) -> str:
    """Build the Claude prompt for generating the file."""

    url_list = "\n".join(f"- {u['url']} ({u['label']})" for u in site_urls[:50]) or "No known pages."

    context = f"""Company: {company_name or 'Unknown'}
Domain: {domain}
Description: {description or 'Not provided.'}
Topics/Keywords: {topics or 'Not provided.'}
Known pages/assets:
{url_list}"""

    if file_type == "llms_txt":
        return f"""Generate an llms.txt file for this company following the llmstxt.org specification.

{context}

The llms.txt file should:
1. Start with a one-line markdown title (# Company Name)
2. Have a brief description paragraph
3. Include sections with links and descriptions of key pages
4. Cover: main site, documentation, blog, product pages, support/contact
5. Use markdown format with descriptive link text

Output ONLY the raw llms.txt content — no explanations, no code fences."""

    elif file_type == "robots_txt":
        return f"""Generate a robots.txt file for this company's website.

{context}

The robots.txt should:
1. Allow all legitimate crawlers (User-agent: *)
2. Explicitly allow AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Google-Extended)
3. Block sensitive paths (/admin, /api, /internal, /private, /_next/data, /wp-admin if applicable)
4. Include a Sitemap: directive pointing to {domain}/sitemap.xml
5. Follow best practices for SEO and GEO (Generative Engine Optimization)

Output ONLY the raw robots.txt content — no explanations, no code fences."""

    elif file_type == "sitemap_xml":
        return f"""Generate a sitemap.xml file for this company's website.

{context}

The sitemap.xml should:
1. Use the standard XML sitemap protocol (xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
2. Include the homepage as highest priority (1.0)
3. Include all known pages from the list above with appropriate priorities
4. Use realistic lastmod dates (today for homepage, recent dates for others)
5. Set changefreq appropriately (daily for homepage/blog, weekly for product pages, monthly for docs)
6. Only include pages that match the domain {domain}
7. If few pages are known, generate reasonable entries based on the company description

Output ONLY the raw sitemap.xml content — no explanations, no code fences."""

    return "Generate a placeholder file."
