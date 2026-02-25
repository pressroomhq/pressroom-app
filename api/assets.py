"""Company Assets — CRUD for discovered and manually added digital assets.

Assets represent a company's digital footprint: subdomains, blogs, docs,
repos, social profiles, API endpoints. Discovered during onboarding or
added manually by the editor.
"""

import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import settings
from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.scout import discover_github_repos

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])


class AssetCreate(BaseModel):
    asset_type: str  # subdomain, blog, docs, repo, social, api_endpoint
    url: str
    label: str = ""
    description: str = ""


class AssetUpdate(BaseModel):
    asset_type: str | None = None
    url: str | None = None
    label: str | None = None
    description: str | None = None


@router.get("")
async def list_assets(type: str | None = None, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List company assets, optionally filtered by type."""
    return await dl.list_assets(asset_type=type)


@router.post("")
async def create_asset(req: AssetCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Manually add a company asset."""
    asset = await dl.save_asset({
        "asset_type": req.asset_type,
        "url": req.url,
        "label": req.label,
        "description": req.description,
        "discovered_via": "manual",
    })
    await dl.commit()
    return asset


@router.put("/{asset_id}")
async def update_asset(asset_id: int, req: AssetUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update an asset's label, description, type, or URL."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        return {"error": "No fields to update"}
    asset = await dl.update_asset(asset_id, **fields)
    if not asset:
        return {"error": "Asset not found"}
    await dl.commit()
    return asset


@router.delete("/{asset_id}")
async def delete_asset(asset_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Remove an asset."""
    deleted = await dl.delete_asset(asset_id)
    if not deleted:
        return {"error": "Asset not found"}
    await dl.commit()
    return {"deleted": asset_id}


@router.post("/github/sync-orgs")
async def sync_github_orgs(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Discover all repos from configured GitHub orgs and add as assets."""
    orgs_raw = await dl.get_setting("scout_github_orgs")
    orgs = json.loads(orgs_raw) if orgs_raw else []
    if not orgs:
        return {"error": "No GitHub organizations configured. Add them in Company settings."}

    gh_token = await dl.get_setting("github_token") or settings.github_token
    existing = {a["url"].lower() for a in await dl.list_assets(asset_type="repo")}

    added = 0
    per_org = {}
    for org_name in orgs:
        try:
            repos = await discover_github_repos(org_name, gh_token=gh_token)
            org_added = 0
            for repo in repos:
                url = f"https://github.com/{repo}"
                if url.lower() not in existing:
                    await dl.save_asset({
                        "asset_type": "repo",
                        "url": url,
                        "label": repo.split("/")[-1],
                        "description": f"From {org_name} org",
                        "discovered_via": "github_org_sync",
                    })
                    existing.add(url.lower())
                    org_added += 1
            per_org[org_name] = {"found": len(repos), "added": org_added}
            added += org_added
            log.info("GITHUB SYNC — %s: %d found, %d new", org_name, len(repos), org_added)
        except Exception as e:
            per_org[org_name] = {"error": str(e)}
            log.warning("GITHUB SYNC — %s failed: %s", org_name, e)

    await dl.commit()
    return {"synced": added, "orgs": per_org}
