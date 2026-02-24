"""Audit endpoints — SEO site audits and GitHub README audits, with persistence."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
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
