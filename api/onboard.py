"""Onboarding API — domain crawl, profile synthesis, DF classification, apply.

Creates an Organization and scopes all settings to it.
"""

import json
import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer, resolve_token
from services.data_layer import DataLayer
from config import settings
from services.onboarding import crawl_domain, synthesize_profile, classify_df_services, profile_to_settings, generate_scout_sources
from services.scout import discover_github_repos
from services.df_client import df

router = APIRouter(prefix="/api/onboard", tags=["onboard"])


# ──────────────────────────────────────
# Request models
# ──────────────────────────────────────

class CrawlRequest(BaseModel):
    domain: str

class ProfileRequest(BaseModel):
    crawl_data: dict | None = None
    domain: str | None = None
    extra_context: str = ""

class ApplyProfileRequest(BaseModel):
    profile: dict
    service_map: dict | None = None
    crawl_pages: dict | None = None  # {label: {url, text}} from crawl step

class ClassifyRequest(BaseModel):
    """Optionally pass pre-fetched service data; otherwise we discover live."""
    pass


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@router.post("/crawl")
async def onboard_crawl(req: CrawlRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Step 1: Crawl a domain and extract page content."""
    if not req.domain:
        return {"error": "Domain is required"}

    data = await crawl_domain(req.domain)
    return data


@router.post("/profile")
async def onboard_profile(req: ProfileRequest, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Step 2: Synthesize a company profile from crawl data.

    If crawl_data not provided, crawls the domain first.
    """
    crawl_data = req.crawl_data
    if not crawl_data and req.domain:
        crawl_data = await crawl_domain(req.domain)

    if not crawl_data:
        return {"error": "Need crawl_data or domain"}

    try:
        api_key = await dl.resolve_api_key()
        profile = await synthesize_profile(crawl_data, req.extra_context, api_key=api_key)
    except anthropic.AuthenticationError:
        return JSONResponse(status_code=401, content={
            "error": "Invalid Anthropic API key. Check your key in Settings and try again."
        })
    except anthropic.APIError as e:
        return JSONResponse(status_code=502, content={
            "error": f"Anthropic API error: {e.message}"
        })

    return {"profile": profile, "crawl": crawl_data}


@router.post("/df-classify")
async def onboard_df_classify(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Step 3: Discover DF services, introspect schemas, classify with Claude.

    Requires DF to be connected (df_base_url + df_api_key in settings).
    """
    if not df.available:
        return {"available": False, "error": "DreamFactory not configured. Set df_base_url and df_api_key first."}

    try:
        api_key = await dl.resolve_api_key()
        db_services = await df.introspect_all_db_services()

        social_services = await df.discover_social_services()
        for svc in social_services:
            try:
                svc["auth_status"] = await df.social_auth_status(svc.get("name", ""))
            except Exception:
                svc["auth_status"] = {"connected": False}

        classification = await classify_df_services(db_services, social_services, api_key=api_key)

        return {
            "available": True,
            "db_services": db_services,
            "social_services": social_services,
            "classification": classification,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.post("/apply")
async def onboard_apply(req: ApplyProfileRequest,
                        dl: DataLayer = Depends(get_authenticated_data_layer),
                        auth_info: dict | None = Depends(resolve_token)):
    """Step 4: Apply the reviewed profile as settings.

    If no org_id in header, creates a new Organization first.
    All settings are scoped to the org.
    """
    company_name = req.profile.get("company_name", "New Company")
    domain = req.profile.get("domain", "")
    user_id = auth_info.get("user_id") if auth_info else None

    # Check if domain already exists before trying to create
    if domain:
        from models import Organization, Profile, UserOrg
        from sqlalchemy import select as sa_select
        existing_org_res = await dl.db.execute(
            sa_select(Organization).where(Organization.domain == domain)
        )
        existing_org = existing_org_res.scalar_one_or_none()
        if existing_org:
            # Check if user is admin
            is_admin = False
            if user_id:
                admin_res = await dl.db.execute(
                    sa_select(Profile.is_admin).where(Profile.id == user_id)
                )
                row = admin_res.scalar_one_or_none()
                is_admin = bool(row)

            if is_admin:
                # Admin: link them to the existing org and return it
                sub_res = await dl.db.execute(
                    sa_select(UserOrg).where(UserOrg.user_id == user_id, UserOrg.org_id == existing_org.id)
                )
                if not sub_res.scalar_one_or_none():
                    dl.db.add(UserOrg(user_id=user_id, org_id=existing_org.id))
                    await dl.db.flush()
                return {
                    "org_id": existing_org.id,
                    "org_name": existing_org.name,
                    "applied": [],
                    "existing": True,
                    "message": f"Loaded existing org for {domain}",
                }
            else:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=409,
                    detail=f"An account for {domain} already exists. Ask a teammate to invite you, or contact support to join their workspace."
                )

    org = await dl.create_org(name=company_name, domain=domain or None)
    org_id = org["id"]
    dl.org_id = org_id
    dl.read_only = False  # we just created it, we own it

    # Link the creating user to this org
    if user_id:
        from models import UserOrg
        from sqlalchemy import select as sa_select
        existing = await dl.db.execute(
            sa_select(UserOrg).where(UserOrg.user_id == user_id, UserOrg.org_id == org_id)
        )
        if not existing.scalar_one_or_none():
            dl.db.add(UserOrg(user_id=user_id, org_id=org_id))
            await dl.db.flush()

    applied = []

    # Convert profile to settings and save
    settings_map = profile_to_settings(req.profile)
    for key, value in settings_map.items():
        await dl.set_setting(key, value)
        applied.append(key)

    # Store company metadata that doesn't map to voice settings
    meta_keys = {
        "company_name": "onboard_company_name",
        "domain": "onboard_domain",
        "industry": "onboard_industry",
        "topics": "onboard_topics",
        "competitors": "onboard_competitors",
    }
    for profile_key, setting_key in meta_keys.items():
        val = req.profile.get(profile_key)
        if val:
            str_val = json.dumps(val) if isinstance(val, (list, dict)) else str(val)
            await dl.set_setting(setting_key, str_val)
            applied.append(setting_key)

    # Store social profiles
    socials = req.profile.get("social_profiles")
    if socials and isinstance(socials, dict):
        await dl.set_setting("social_profiles", json.dumps(socials))
        applied.append("social_profiles")

    # Store DF service map if provided
    if req.service_map:
        await dl.set_setting("df_service_map", json.dumps(req.service_map))
        applied.append("df_service_map")

    # Generate smart scout sources from the profile
    api_key = await dl.resolve_api_key()
    try:
        scout_sources = await generate_scout_sources(req.profile, api_key=api_key)
        if scout_sources:
            if scout_sources.get("subreddits"):
                await dl.set_setting("scout_subreddits", json.dumps(scout_sources["subreddits"]))
                applied.append("scout_subreddits")
            if scout_sources.get("hn_keywords"):
                await dl.set_setting("scout_hn_keywords", json.dumps(scout_sources["hn_keywords"]))
                applied.append("scout_hn_keywords")
            if scout_sources.get("rss_feeds"):
                await dl.set_setting("scout_rss_feeds", json.dumps(scout_sources["rss_feeds"]))
                applied.append("scout_rss_feeds")
            if scout_sources.get("web_queries"):
                await dl.set_setting("scout_web_queries", json.dumps(scout_sources["web_queries"]))
                applied.append("scout_web_queries")
    except Exception:
        pass  # Non-fatal — scout sources are nice to have

    # Discover GitHub repos from social profile (way better than LLM guessing)
    try:
        import re as _re
        github_url = ""
        if socials and isinstance(socials, dict):
            github_url = socials.get("github", "")

        if github_url:
            # Use org DB token first, fall back to app-level token
            gh_token = await dl.get_setting("github_token") or settings.github_token
            discovered_repos = await discover_github_repos(github_url, gh_token=gh_token)
            if discovered_repos:
                await dl.set_setting("scout_github_repos", json.dumps(discovered_repos))
                applied.append("scout_github_repos")

            # Also auto-create a github_org wire source so releases/commits flow into Wire
            # Extract owner from URL — works whether it's an org URL or a specific repo URL
            owner_match = _re.search(r'github\.com/([^/\s?#]+)', github_url)
            if owner_match:
                from models import WireSource
                from sqlalchemy import select as sa_select
                owner = owner_match.group(1)
                # Only create if one doesn't already exist for this owner
                existing_ws = await dl.db.execute(
                    sa_select(WireSource).where(
                        WireSource.org_id == dl.org_id,
                        WireSource.type == "github_org",
                    )
                )
                if not existing_ws.scalar_one_or_none():
                    ws = WireSource(
                        org_id=dl.org_id,
                        type="github_org",
                        name=f"{owner} (GitHub)",
                        config=json.dumps({"org": owner}),
                        active=True,
                    )
                    dl.db.add(ws)
                    applied.append("wire_github_org")

        elif scout_sources and scout_sources.get("github_repos"):
            # Fallback to LLM-guessed repos if no GitHub social profile
            await dl.set_setting("scout_github_repos", json.dumps(scout_sources["github_repos"]))
            applied.append("scout_github_repos")
    except Exception:
        pass  # Non-fatal

    # ── Persist discovered assets as CompanyAsset records ──
    asset_count = 0

    # Crawl pages → assets (blog, docs, subdomains, etc.)
    crawl_pages = req.crawl_pages or {}
    for label, page_data in crawl_pages.items():
        url = page_data.get("url", "") if isinstance(page_data, dict) else str(page_data)
        if not url:
            continue
        # Map crawl labels to asset types
        if label.startswith("sub:"):
            sub_name = label.removeprefix("sub:")
            # Blog subdomains (blog.example.com) should be typed as "blog" not "subdomain"
            if sub_name in ("blog", "news", "articles"):
                asset_type = "blog"
            else:
                asset_type = "subdomain"
            asset_label = sub_name
        elif label in ("blog", "news", "articles"):
            asset_type = "blog"
            asset_label = label
        elif label in ("docs", "documentation", "api", "reference", "guides"):
            asset_type = "docs"
            asset_label = label
        elif label in ("product", "features", "platform", "solutions"):
            asset_type = "product"
            asset_label = label
        else:
            asset_type = "page"
            asset_label = label
        await dl.save_asset({
            "asset_type": asset_type,
            "url": url,
            "label": asset_label,
            "description": "",
            "discovered_via": "onboarding",
            "auto_discovered": True,
        })
        asset_count += 1

    # Build company_properties from discovered crawl pages
    prop_map = {
        "docs": ("docs", "documentation", "api", "reference", "guides", "sub:docs", "sub:developers", "sub:api"),
        "support": ("contact", "support", "help", "sub:help", "sub:support"),
        "pricing": ("pricing",),
        "careers": ("careers", "jobs", "hiring"),
        "customers": ("customers", "case-studies", "testimonials"),
        "changelog": ("changelog", "releases", "whats-new"),
        "status": ("sub:status",),
        "newsletter": ("newsletter", "subscribe"),
    }
    props = {}
    for prop_key, labels in prop_map.items():
        for label in labels:
            if label in crawl_pages:
                page_data = crawl_pages[label]
                url = page_data.get("url", "") if isinstance(page_data, dict) else str(page_data)
                if url:
                    props[prop_key] = url
                    break
    if props:
        await dl.set_setting("company_properties", json.dumps(props))
        applied.append("company_properties")

    # Social profiles → assets
    if socials and isinstance(socials, dict):
        for platform, url in socials.items():
            if url:
                await dl.save_asset({
                    "asset_type": "social",
                    "url": url,
                    "label": platform,
                    "description": f"{platform} profile",
                    "discovered_via": "onboarding",
                    "auto_discovered": True,
                })
                asset_count += 1

    # GitHub repos → assets (if discovered)
    try:
        repos_json = await dl.get_setting("scout_github_repos")
        if repos_json:
            repos = json.loads(repos_json)
            for repo in (repos if isinstance(repos, list) else []):
                repo_name = repo if isinstance(repo, str) else repo.get("full_name", repo.get("name", ""))
                if repo_name:
                    await dl.save_asset({
                        "asset_type": "repo",
                        "url": f"https://github.com/{repo_name}" if "/" in repo_name else repo_name,
                        "label": repo_name.split("/")[-1] if "/" in repo_name else repo_name,
                        "description": repo.get("description", "") if isinstance(repo, dict) else "",
                        "discovered_via": "onboarding",
                        "auto_discovered": True,
                    })
                    asset_count += 1
    except Exception:
        pass  # Non-fatal

    # Auto-scrape blog if a blog asset was discovered
    blog_scrape_count = 0
    blog_labels = ("blog", "news", "articles", "sub:blog", "sub:news", "sub:articles")
    blog_assets = [
        {"url": page_data.get("url", "") if isinstance(page_data, dict) else str(page_data)}
        for label, page_data in crawl_pages.items()
        if label in blog_labels
    ]
    if blog_assets:
        try:
            from services.blog_scraper import scrape_blog_posts
            for ba in blog_assets:
                url = ba.get("url", "")
                if not url:
                    continue
                posts = await scrape_blog_posts(url, days=30, api_key=api_key)
                for p in posts:
                    await dl.save_blog_post(p)
                    blog_scrape_count += 1
        except Exception:
            pass  # Non-fatal — blog scrape is best-effort

    # Mark onboarding as complete
    await dl.set_setting("onboard_complete", "true")
    applied.append("onboard_complete")

    await dl.commit()

    # Sync to runtime config
    from api.settings import _sync_to_runtime
    await _sync_to_runtime(dl)

    return {"applied": applied, "count": len(applied), "org_id": org_id, "org": org,
            "blog_posts_scraped": blog_scrape_count}


@router.get("/status")
async def onboard_status(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Check onboarding progress — what's been completed."""
    stored = await dl.get_all_settings()

    return {
        "complete": stored.get("onboard_complete") == "true",
        "has_company": bool(stored.get("onboard_company_name")),
        "has_voice": bool(stored.get("voice_persona")),
        "has_df": bool(stored.get("df_api_key")),
        "has_service_map": bool(stored.get("df_service_map")),
        "company_name": stored.get("onboard_company_name", ""),
        "industry": stored.get("onboard_industry", ""),
        "org_id": dl.org_id,
    }
