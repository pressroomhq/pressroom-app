"""Data Sources — CRUD for external data connections.

Users add named connections like "Intercom Data" or "HubSpot DB" with a
category and connection details. These feed intelligence into the content engine.
"""

import json
import logging
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/datasources", tags=["datasources"])


class DataSourceCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "database"          # database, crm, analytics, support, custom
    connection_type: str = "mcp"  # mcp, rest_api
    base_url: str = ""
    api_key: str = ""
    config: str = "{}"


class DataSourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    config: str | None = None


@router.get("")
async def list_datasources(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List all data sources for this org."""
    return await dl.list_datasources()


@router.post("")
async def create_datasource(req: DataSourceCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Add a new data source."""
    return await dl.save_datasource({
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "connection_type": req.connection_type,
        "base_url": req.base_url,
        "api_key": req.api_key,
        "config": req.config,
    })


@router.put("/{ds_id}")
async def update_datasource(ds_id: int, req: DataSourceUpdate,
                            dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update a data source."""
    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.description is not None:
        updates["description"] = req.description
    if req.category is not None:
        updates["category"] = req.category
    if req.base_url is not None:
        updates["base_url"] = req.base_url
    if req.api_key is not None:
        updates["api_key"] = req.api_key
    if req.config is not None:
        updates["config"] = req.config

    result = await dl.update_datasource(ds_id, **updates)
    if not result:
        return {"error": "Not found"}
    await dl.commit()
    return result


@router.delete("/{ds_id}")
async def delete_datasource(ds_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Remove a data source."""
    deleted = await dl.delete_datasource(ds_id)
    if not deleted:
        return {"error": "Not found"}
    await dl.commit()
    return {"deleted": ds_id}


@router.post("/{ds_id}/test")
async def test_datasource(ds_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Test connectivity to a data source."""
    ds_list = await dl.list_datasources()
    ds = next((d for d in ds_list if d["id"] == ds_id), None)
    if not ds:
        return {"error": "Not found"}

    connection_type = ds.get("connection_type", "mcp")
    base_url = ds.get("base_url", "")
    has_key = ds.get("api_key_set", False)

    if connection_type == "mcp":
        if not base_url:
            return {"connected": False, "error": "Missing MCP server URL"}
        try:
            # We don't expose the raw api_key in list results — re-fetch from DB
            from sqlalchemy import select
            from models import DataSource
            result = await dl.db.execute(
                select(DataSource).where(DataSource.id == ds_id, DataSource.org_id == dl.org_id)
            )
            ds_obj = result.scalar_one_or_none()
            if not ds_obj:
                return {"error": "Not found"}

            headers = {}
            if ds_obj.api_key:
                headers["X-DreamFactory-Api-Key"] = ds_obj.api_key
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(base_url.rstrip("/"), headers=headers)
                if resp.status_code < 400:
                    return {"connected": True, "detail": f"MCP server responding (HTTP {resp.status_code})"}
                return {"connected": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    elif connection_type == "rest_api":
        if not base_url:
            return {"connected": False, "error": "Missing base URL"}
        try:
            from sqlalchemy import select
            from models import DataSource
            result = await dl.db.execute(
                select(DataSource).where(DataSource.id == ds_id, DataSource.org_id == dl.org_id)
            )
            ds_obj = result.scalar_one_or_none()
            if not ds_obj:
                return {"error": "Not found"}

            headers = {}
            if ds_obj.api_key:
                headers["Authorization"] = f"Bearer {ds_obj.api_key}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(base_url, headers=headers)
                return {"connected": resp.status_code < 400, "status": resp.status_code}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    return {"connected": False, "error": f"Unknown connection type: {connection_type}"}
