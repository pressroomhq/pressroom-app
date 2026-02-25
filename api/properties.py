"""Site Properties — bonded site + repo pairs for SEO workflows."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/properties", tags=["properties"])


class PropertyCreate(BaseModel):
    name: str
    domain: str
    repo_url: str = ""
    base_branch: str = "main"
    site_type: str = "static"  # static, cms, app


class PropertyUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    repo_url: str | None = None
    base_branch: str | None = None
    site_type: str | None = None
    last_audit_score: int | None = None
    last_audit_id: int | None = None


@router.get("")
async def list_properties(dl: DataLayer = Depends(get_authenticated_data_layer)):
    return await dl.list_site_properties()


@router.post("")
async def create_property(req: PropertyCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    if not req.name.strip() or not req.domain.strip():
        return {"error": "Name and domain are required."}
    prop = await dl.save_site_property({
        "name": req.name.strip(),
        "domain": req.domain.strip(),
        "repo_url": req.repo_url.strip(),
        "base_branch": req.base_branch.strip() or "main",
        "site_type": req.site_type or "static",
    })
    await dl.commit()
    return prop


@router.put("/{prop_id}")
async def update_property(prop_id: int, req: PropertyUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        return {"error": "No fields to update"}
    prop = await dl.update_site_property(prop_id, **fields)
    if not prop:
        return {"error": "Property not found"}
    await dl.commit()
    return prop


@router.delete("/{prop_id}")
async def delete_property(prop_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    deleted = await dl.delete_site_property(prop_id)
    if not deleted:
        return {"error": "Property not found"}
    await dl.commit()
    return {"deleted": prop_id}
