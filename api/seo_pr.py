"""SEO PR Workflow endpoints — start pipeline runs, check status, view plans."""

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from database import async_session
from services.data_layer import DataLayer
from api.auth import get_authenticated_data_layer
from services.seo_pipeline import run_seo_pipeline

router = APIRouter(prefix="/api/seo-pr", tags=["seo-pr"])
log = logging.getLogger("pressroom.seo_pr")


class SeoPrRunRequest(BaseModel):
    repo_url: str
    domain: str = ""
    base_branch: str = "main"
    action_items: list[dict] = []  # if provided, skip re-audit and use these findings


@router.post("/run")
async def start_seo_pr_run(
    req: SeoPrRunRequest,
    background_tasks: BackgroundTasks,
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """Start a new SEO PR pipeline run. Returns immediately with run ID."""
    domain = req.domain
    if not domain:
        # Try to get domain from org settings
        settings = await dl.get_all_settings()
        domain = settings.get("onboard_domain", "")
        if not domain and dl.org_id:
            org = await dl.get_org(dl.org_id)
            domain = org.get("domain", "") if org else ""

    if not domain:
        return {"error": "No domain specified and no org domain found."}

    if not req.repo_url:
        return {"error": "repo_url is required."}

    # Resolve API key
    api_key = await dl.resolve_api_key()
    if not api_key:
        return {"error": "No Anthropic API key configured. Add one in Account settings."}

    # Get company context for the analysis
    all_settings = await dl.get_all_settings()
    company_description = all_settings.get("golden_anchor", all_settings.get("onboard_company_description", ""))

    # Create the run record
    run_data = await dl.save_seo_pr_run({
        "domain": domain,
        "repo_url": req.repo_url,
        "status": "pending",
    })
    await dl.commit()

    run_id = run_data["id"]
    org_id = dl.org_id

    # Launch pipeline in background
    config = {
        "domain": domain,
        "repo_url": req.repo_url,
        "base_branch": req.base_branch,
        "run_id": run_id,
        "company_description": company_description,
        "action_items": req.action_items,  # skip re-audit if provided
    }

    background_tasks.add_task(_run_pipeline_bg, run_id, org_id, config, api_key)

    return {"id": run_id, "status": "pending", "domain": domain}


async def _run_pipeline_bg(run_id: int, org_id: int | None, config: dict, api_key: str):
    """Background task that runs the SEO pipeline and updates the DB."""
    async def update_fn(updates: dict):
        async with async_session() as session:
            from services.data_layer import DataLayer
            bg_dl = DataLayer(session, org_id=org_id)
            await bg_dl.update_seo_pr_run(run_id, updates)
            await bg_dl.commit()

    try:
        result = await run_seo_pipeline(org_id, config, api_key, update_fn=update_fn)
        log.info("[SEO PR] Run %d complete: status=%s, pr=%s", run_id, result.get("status"), result.get("pr_url"))
    except Exception as e:
        log.error("[SEO PR] Run %d failed: %s", run_id, e, exc_info=True)
        try:
            await update_fn({"status": "failed", "error": str(e)})
        except Exception:
            pass


@router.get("/runs")
async def list_runs(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List all SEO PR runs for the org."""
    return await dl.list_seo_pr_runs(limit=20)


@router.get("/runs/{run_id}")
async def get_run(run_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get run details (status, plan, PR URL)."""
    run = await dl.get_seo_pr_run(run_id)
    if not run:
        return {"error": "Run not found"}
    return run


@router.get("/runs/{run_id}/plan")
async def get_run_plan(run_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get the tiered plan JSON for a run."""
    run = await dl.get_seo_pr_run(run_id)
    if not run:
        return {"error": "Run not found"}
    return run.get("plan", {})


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Delete a run record."""
    deleted = await dl.delete_seo_pr_run(run_id)
    await dl.commit()
    if not deleted:
        return {"error": "Run not found"}
    return {"deleted": run_id}
