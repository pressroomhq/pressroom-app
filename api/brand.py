"""Brand API — scrape and store per-org visual identity."""

import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.brand_scraper import scrape_brand

router = APIRouter(prefix="/api/brand", tags=["brand"])


class ScrapeRequest(BaseModel):
    url: str = ""


@router.post("/scrape")
async def run_brand_scrape(req: ScrapeRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Scrape a company's website for brand assets (logo, colors, fonts)."""
    url = req.url
    if not url:
        settings = await dl.get_all_settings()
        url = settings.get("onboard_domain", "")
        if not url:
            org = await dl.get_org(dl.org_id) if dl.org_id else None
            url = org.get("domain", "") if org else ""

    if not url:
        return {"error": "No URL provided and no org domain found."}

    # Ensure URL has scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    brand = await scrape_brand(url)

    # Save to org settings
    if dl.org_id:
        await dl.set_setting("brand_data", json.dumps(brand))
        await dl.commit()

    return brand


@router.post("/crawl-target")
async def crawl_target_brand(req: ScrapeRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Crawl a target company's website for brand assets without saving.

    Used for personalized video generation — returns brand data for the
    target company so it can be injected into the Remotion package.
    """
    url = req.url
    if not url:
        return {"error": "URL is required."}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return await scrape_brand(url)


@router.get("/{org_id}")
async def get_brand(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return stored brand data for the authenticated org."""
    # Use the authenticated org_id, not the path parameter (prevents IDOR)
    settings = await dl.get_all_settings()
    raw = settings.get("brand_data", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {
        "logo_url": None,
        "primary_color": None,
        "secondary_color": None,
        "font_family": None,
        "company_name": None,
        "favicon_url": None,
    }
