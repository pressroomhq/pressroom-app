"""Blog API — scrape, list, and manage scraped blog posts."""

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import get_data_layer
from services.data_layer import DataLayer
from services.blog_scraper import scrape_blog_posts

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/blog", tags=["blog"])


class ScrapeRequest(BaseModel):
    blog_url: str = ""


@router.post("/scrape")
async def scrape_blog(req: ScrapeRequest, dl: DataLayer = Depends(get_data_layer)):
    """Scrape blog posts from a URL.

    If blog_url not provided, auto-detects from org assets (looks for blog-type assets).
    """
    blog_url = req.blog_url.strip()

    # Primary: read from social_profiles.blog in Company settings
    if not blog_url:
        try:
            sp_raw = await dl.get_setting("social_profiles")
            sp = json.loads(sp_raw) if sp_raw else {}
            blog_url = (sp.get("blog") or "").strip()
        except Exception:
            pass

    # Fallback: check assets for blog-type entries
    if not blog_url:
        assets = await dl.list_assets(asset_type="blog")
        if assets:
            blog_url = assets[0]["url"]

    if not blog_url:
        return {"error": "No blog URL configured. Set it in Config → Company → Social Profiles."}

    api_key = await dl.resolve_api_key()
    try:
        posts = await scrape_blog_posts(blog_url, days=30, api_key=api_key)
    except Exception as e:
        log.error("BLOG SCRAPE FAILED — %s: %s", blog_url, str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Blog scrape failed: {str(e)}", "blog_url": blog_url},
        )

    if not posts:
        return {"blog_url": blog_url, "posts_found": 0, "posts_saved": 0,
                "message": "No posts found. The blog may not have an RSS feed or recognizable post URLs."}

    # Save posts, skip duplicates by URL
    existing = await dl.list_blog_posts(limit=200)
    existing_urls = {bp["url"] for bp in existing}

    saved = 0
    for p in posts:
        if p.get("url") and p["url"] not in existing_urls:
            await dl.save_blog_post(p)
            existing_urls.add(p["url"])
            saved += 1

    await dl.commit()

    log.info("BLOG SCRAPE — %s: %d found, %d saved", blog_url, len(posts), saved)

    return {
        "blog_url": blog_url,
        "posts_found": len(posts),
        "posts_saved": saved,
        "posts_skipped": len(posts) - saved,
    }


@router.get("/posts")
async def list_posts(dl: DataLayer = Depends(get_data_layer)):
    """List scraped blog posts for the current org."""
    return await dl.list_blog_posts(limit=50)


@router.delete("/posts/{post_id}")
async def delete_post(post_id: int, dl: DataLayer = Depends(get_data_layer)):
    """Delete a scraped blog post."""
    deleted = await dl.delete_blog_post(post_id)
    if not deleted:
        return {"error": "Post not found"}
    await dl.commit()
    return {"deleted": post_id}
