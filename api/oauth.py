"""OAuth callback endpoints — LinkedIn + Facebook.

Flow:
  1. Frontend calls GET /api/oauth/linkedin?org_id=N
  2. We redirect to LinkedIn's auth page
  3. LinkedIn redirects back to GET /api/oauth/linkedin/callback?code=...&state=...
  4. We exchange code for token, store per-org, redirect back to frontend
"""

import json
import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse

from database import get_data_layer, async_session
from services.data_layer import DataLayer
from services import social_auth

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _base_url(request: Request) -> str:
    """Derive the external base URL from the incoming request."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}"


# ──────────────────────────────────────
# LinkedIn
# ──────────────────────────────────────

@router.get("/linkedin")
async def linkedin_start(request: Request, org_id: int = 0,
                         dl: DataLayer = Depends(get_data_layer)):
    """Redirect user to LinkedIn authorization page."""
    settings = await dl.get_all_settings()
    client_id = settings.get("linkedin_client_id", "")
    # Fall back to global settings if not set at org level
    if not client_id:
        async with async_session() as session:
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            client_id = global_settings.get("linkedin_client_id", "")
    if not client_id:
        return JSONResponse(status_code=400, content={
            "error": "LinkedIn Client ID not configured. Set it in Settings → OAuth App Credentials."
        })

    redirect_uri = f"{_base_url(request)}/api/oauth/linkedin/callback"
    state = str(org_id)  # pass org_id through OAuth state
    auth_url = social_auth.linkedin_auth_url(client_id, redirect_uri, state=state)
    return RedirectResponse(url=auth_url)


@router.get("/linkedin/callback")
async def linkedin_callback(request: Request, code: str = "", state: str = "",
                            error: str = ""):
    """Handle LinkedIn OAuth callback — exchange code, store tokens."""
    if error or not code:
        log.error("LinkedIn OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=linkedin")

    org_id = int(state) if state.isdigit() else None

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        # Also check global settings if org-level not set
        if not settings.get("linkedin_client_id"):
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            settings = {**global_settings, **settings}

        client_id = settings.get("linkedin_client_id", "")
        client_secret = settings.get("linkedin_client_secret", "")

        if not client_id or not client_secret:
            return RedirectResponse(url="/?oauth=error&provider=linkedin&reason=no_credentials")

        redirect_uri = f"{_base_url(request)}/api/oauth/linkedin/callback"
        result = await social_auth.linkedin_exchange_code(
            client_id, client_secret, code, redirect_uri
        )

        if "error" in result:
            log.error("LinkedIn token exchange failed: %s", result["error"])
            return RedirectResponse(url="/?oauth=error&provider=linkedin")

        # Store tokens per-org
        await dl.set_setting("linkedin_access_token", result.get("access_token", ""))
        sub = result.get("sub", "")
        if sub:
            await dl.set_setting("linkedin_author_urn", f"urn:li:person:{sub}")
        await dl.set_setting("linkedin_profile_name", result.get("name", ""))
        # Track token expiration (LinkedIn tokens last ~60 days)
        expires_in = result.get("expires_in", 5184000)
        await dl.set_setting("linkedin_token_expires_at", str(int(time.time()) + int(expires_in)))
        await dl.commit()

        log.info("LinkedIn OAuth complete for org %s — user: %s", org_id, result.get("name", "?"))
        return RedirectResponse(url="/?oauth=success&provider=linkedin")


# ──────────────────────────────────────
# Facebook
# ──────────────────────────────────────

@router.get("/facebook")
async def facebook_start(request: Request, org_id: int = 0,
                         dl: DataLayer = Depends(get_data_layer)):
    """Redirect user to Facebook authorization page."""
    settings = await dl.get_all_settings()
    app_id = settings.get("facebook_app_id", "")
    if not app_id:
        return JSONResponse(status_code=400, content={
            "error": "Facebook App ID not configured. Set it in Config."
        })

    redirect_uri = f"{_base_url(request)}/api/oauth/facebook/callback"
    state = str(org_id)
    auth_url = social_auth.facebook_auth_url(app_id, redirect_uri, state=state)
    return RedirectResponse(url=auth_url)


@router.get("/facebook/callback")
async def facebook_callback(request: Request, code: str = "", state: str = "",
                            error: str = ""):
    """Handle Facebook OAuth callback — exchange code, store page token."""
    if error or not code:
        log.error("Facebook OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=facebook")

    org_id = int(state) if state.isdigit() else None

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        if not settings.get("facebook_app_id"):
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            settings = {**global_settings, **settings}

        app_id = settings.get("facebook_app_id", "")
        app_secret = settings.get("facebook_app_secret", "")

        if not app_id or not app_secret:
            return RedirectResponse(url="/?oauth=error&provider=facebook&reason=no_credentials")

        redirect_uri = f"{_base_url(request)}/api/oauth/facebook/callback"
        result = await social_auth.facebook_exchange_code(
            app_id, app_secret, code, redirect_uri
        )

        if "error" in result:
            log.error("Facebook token exchange failed: %s", result["error"])
            return RedirectResponse(url="/?oauth=error&provider=facebook")

        # Store first page token (most common case — single page)
        pages = result.get("pages", [])
        if pages:
            page = pages[0]
            await dl.set_setting("facebook_page_token", page.get("access_token", ""))
            await dl.set_setting("facebook_page_id", page.get("id", ""))
            await dl.set_setting("facebook_page_name", page.get("name", ""))

        await dl.commit()

        page_count = len(pages)
        log.info("Facebook OAuth complete for org %s — %d pages found", org_id, page_count)
        return RedirectResponse(url="/?oauth=success&provider=facebook")


# ──────────────────────────────────────
# Connection status
# ──────────────────────────────────────

@router.get("/status")
async def oauth_status(dl: DataLayer = Depends(get_data_layer)):
    """Check which social accounts are connected for this org."""
    settings = await dl.get_all_settings()

    # Also pull global settings for app credentials
    global_settings = {}
    if dl.org_id:
        async with async_session() as session:
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()

    all_settings = {**global_settings, **settings}

    # LinkedIn token health
    li_expires_at = settings.get("linkedin_token_expires_at", "")
    li_expires_ts = int(li_expires_at) if li_expires_at.isdigit() else 0
    li_healthy = li_expires_ts > int(time.time()) + 3600 if li_expires_ts else False
    li_days_left = max(0, (li_expires_ts - int(time.time())) // 86400) if li_expires_ts else 0

    return {
        "linkedin": {
            "app_configured": bool(all_settings.get("linkedin_client_id")),
            "connected": bool(settings.get("linkedin_access_token")),
            "profile_name": settings.get("linkedin_profile_name", ""),
            "token_healthy": li_healthy,
            "days_remaining": li_days_left,
        },
        "facebook": {
            "app_configured": bool(all_settings.get("facebook_app_id")),
            "connected": bool(settings.get("facebook_page_token")),
            "page_name": settings.get("facebook_page_name", ""),
        },
    }
