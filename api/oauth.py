"""OAuth callback endpoints — LinkedIn + Facebook.

Flow:
  1. Frontend calls GET /api/oauth/linkedin?org_id=N
  2. We redirect to LinkedIn's auth page
  3. LinkedIn redirects back to GET /api/oauth/linkedin/callback?code=...&state=...
  4. We exchange code for token, store per-org, redirect back to frontend
"""

import base64
import httpx
import json
import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse

from config import settings as app_cfg
from database import async_session
from services.data_layer import DataLayer
from api.auth import get_authenticated_data_layer, resolve_token
from services import social_auth

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _base_url(request: Request) -> str:
    """Derive the external base URL from the incoming request.

    Prefers the Origin/Referer header (reflects the browser-facing URL,
    not the proxied backend URL behind Vite or nginx).
    """
    from urllib.parse import urlparse
    referer = request.headers.get("referer", "")
    if referer:
        p = urlparse(referer)
        return f"{p.scheme}://{p.netloc}"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}"


def _encode_state(**kwargs) -> str:
    """Encode OAuth state as base64-JSON (org_id, member_id, origin, etc.)."""
    return base64.urlsafe_b64encode(json.dumps(kwargs).encode()).decode().rstrip("=")


def _decode_state(state: str) -> dict:
    """Decode OAuth state from base64-JSON, with fallback for legacy plain states."""
    if not state:
        return {}
    # Legacy format: "org_id" or "org_id:member_id"
    if state.isdigit() or (state.count(":") == 1 and all(p.isdigit() for p in state.split(":"))):
        parts = state.split(":")
        d = {"org_id": int(parts[0])}
        if len(parts) > 1:
            d["member_id"] = int(parts[1])
        return d
    # New base64-JSON format
    try:
        padded = state + "=" * (-len(state) % 4)
        return json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception:
        return {}


# ──────────────────────────────────────
# LinkedIn
# ──────────────────────────────────────

@router.get("/linkedin")
async def linkedin_start(request: Request, org_id: int = 0, member_id: int = 0,
                         user_id: str = ""):
    """Redirect user to LinkedIn authorization page.

    user_id: Supabase user UUID — token stored on their profile (account-level).
    member_id: team member ID — token stored on that team member row.
    No auth required — this is a browser redirect (window.open), not an API call.
    """
    # Resolve client_id: DB settings → .env
    client_id = app_cfg.linkedin_client_id
    if not client_id:
        async with async_session() as session:
            from services.data_layer import DataLayer as DL
            global_dl = DL(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            client_id = global_settings.get("linkedin_client_id", "")
    if not client_id:
        return JSONResponse(status_code=400, content={
            "error": "LinkedIn Client ID not configured. Set it in Settings → OAuth App Credentials."
        })

    origin = _base_url(request)
    redirect_uri = f"{origin}/api/oauth/linkedin/callback"
    state = _encode_state(org_id=org_id, member_id=member_id, user_id=user_id, origin=origin)
    auth_url = social_auth.linkedin_auth_url(client_id, redirect_uri, state=state)
    return RedirectResponse(url=auth_url)


@router.get("/linkedin/callback")
async def linkedin_callback(request: Request, code: str = "", state: str = "",
                            error: str = ""):
    """Handle LinkedIn OAuth callback — exchange code, store tokens."""
    if error or not code:
        log.error("LinkedIn OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=linkedin")

    # Decode state (supports both legacy "org_id:member_id" and new base64-JSON)
    sd = _decode_state(state)
    org_id = sd.get("org_id")
    member_id = sd.get("member_id")
    user_id = sd.get("user_id", "")
    origin = sd.get("origin", "")

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        # Also check global settings if org-level not set
        if not settings.get("linkedin_client_id"):
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            settings = {**global_settings, **settings}

        client_id = settings.get("linkedin_client_id", "") or app_cfg.linkedin_client_id
        client_secret = settings.get("linkedin_client_secret", "") or app_cfg.linkedin_client_secret

        if not client_id or not client_secret:
            return RedirectResponse(url="/?oauth=error&provider=linkedin&reason=no_credentials")

        # Use the same origin from the initial redirect to ensure redirect_uri matches
        base = origin or _base_url(request)
        redirect_uri = f"{base}/api/oauth/linkedin/callback"
        result = await social_auth.linkedin_exchange_code(
            client_id, client_secret, code, redirect_uri
        )

        if "error" in result:
            log.error("LinkedIn token exchange failed: %s", result["error"])
            return RedirectResponse(url="/?oauth=error&provider=linkedin")

        access_token = result.get("access_token", "")
        sub = result.get("sub", "")
        author_urn = f"urn:li:person:{sub}" if sub else ""
        name = result.get("name", "")
        expires_in = result.get("expires_in", 5184000)
        expires_at = int(time.time()) + int(expires_in)

        if member_id:
            # Store on the specific team member row
            from sqlalchemy import select as sa_select, update as sa_update
            from models import TeamMember
            await session.execute(
                sa_update(TeamMember)
                .where(TeamMember.id == member_id)
                .values(
                    linkedin_access_token=access_token,
                    linkedin_author_urn=author_urn,
                    linkedin_token_expires_at=expires_at,
                )
            )
            await session.commit()
            log.info("LinkedIn OAuth complete for member %s — user: %s", member_id, name)
            return RedirectResponse(url=f"/?oauth=success&provider=linkedin&for=member&name={name}")
        elif user_id:
            # Store on the user's profile (account-level, not org-level)
            from sqlalchemy import update as sa_update
            from models import Profile
            await session.execute(
                sa_update(Profile)
                .where(Profile.id == user_id)
                .values(
                    linkedin_access_token=access_token,
                    linkedin_author_urn=author_urn,
                    linkedin_profile_name=name,
                    linkedin_token_expires_at=expires_at,
                )
            )
            await session.commit()
            log.info("LinkedIn OAuth complete for user %s — name: %s", user_id, name)
            return RedirectResponse(url=f"/?oauth=success&provider=linkedin&name={name}")
        else:
            # Legacy fallback: store at org level
            await dl.set_setting("linkedin_access_token", access_token)
            if author_urn:
                await dl.set_setting("linkedin_author_urn", author_urn)
            await dl.set_setting("linkedin_profile_name", name)
            await dl.set_setting("linkedin_token_expires_at", str(expires_at))
            await dl.commit()
            log.info("LinkedIn OAuth complete for org %s — user: %s", org_id, name)
            return RedirectResponse(url="/?oauth=success&provider=linkedin")


@router.post("/linkedin/analyze-voice")
async def linkedin_analyze_voice(dl: DataLayer = Depends(get_authenticated_data_layer),
                                 auth_info: dict | None = Depends(resolve_token)):
    """Fetch recent LinkedIn posts and extract voice/style into voice_linkedin_style setting."""
    token = ""
    author_urn = ""

    # Read from user's profile (account-level)
    user_id = auth_info.get("user_id") if auth_info else None
    if user_id:
        from sqlalchemy import select as sa_select
        from models import Profile
        async with async_session() as session:
            result = await session.execute(sa_select(Profile).where(Profile.id == user_id))
            profile = result.scalar_one_or_none()
            if profile:
                token = profile.linkedin_access_token or ""
                author_urn = profile.linkedin_author_urn or ""

    # Fallback to org settings
    if not token or not author_urn:
        settings = await dl.get_all_settings()
        token = token or settings.get("linkedin_access_token", "")
        author_urn = author_urn or settings.get("linkedin_author_urn", "")

    if not token or not author_urn:
        return {"error": "LinkedIn not connected — connect it first in Connections."}

    from config import settings as app_settings
    import anthropic

    # Fetch recent posts by this author using the REST Posts API
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization": f"Bearer {token}",
                "LinkedIn-Version": "202402",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            params={
                "author": author_urn,
                "q": "author",
                "count": 20,
                "sortBy": "LAST_MODIFIED",
            },
        )

    if resp.status_code == 401:
        return {"error": "LinkedIn token expired — reconnect in Connections."}
    if resp.status_code == 403:
        return {"error": "LinkedIn API access denied — your app may need r_member_social scope approval from LinkedIn."}
    if resp.status_code != 200:
        log.error("LinkedIn posts fetch failed: %s %s", resp.status_code, resp.text[:300])
        return {"error": f"LinkedIn API error {resp.status_code} — try reconnecting."}

    data = resp.json()
    elements = data.get("elements", [])
    if not elements:
        return {"error": "No posts found on this LinkedIn profile yet."}

    # Extract post text from commentary field
    post_texts = []
    for el in elements:
        text = el.get("commentary", "")
        if text and len(text.strip()) > 20:
            post_texts.append(text.strip())

    if not post_texts:
        return {"error": "Found posts but couldn't extract text content."}

    key = app_settings.anthropic_api_key
    if not key:
        return {"error": "No Anthropic API key configured."}

    # Analyze voice from posts
    posts_sample = "\n\n---\n\n".join(post_texts[:15])
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system="""Analyze LinkedIn posts and extract the author's writing voice and style.
Be specific and concrete — describe HOW they write, not just what they write about.
Keep your response to 3-5 sentences max.""",
        messages=[{"role": "user", "content": f"""Here are {len(post_texts)} recent LinkedIn posts from this person:

{posts_sample}

Describe their LinkedIn writing style: sentence length, tone (personal/professional/conversational),
use of formatting (bullets/line breaks/emojis), how they open posts, storytelling patterns,
vocabulary level, and anything distinctive about how they communicate."""}],
    )

    style_description = response.content[0].text.strip()

    # Save to voice setting
    await dl.set_setting("voice_linkedin_style", style_description)
    await dl.commit()

    return {
        "success": True,
        "posts_analyzed": len(post_texts),
        "style": style_description,
    }


# ──────────────────────────────────────
# Facebook
# ──────────────────────────────────────

@router.get("/facebook")
async def facebook_start(request: Request, org_id: int = 0,
                         dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Redirect user to Facebook authorization page."""
    settings = await dl.get_all_settings()
    app_id = settings.get("facebook_app_id", "")
    if not app_id:
        return JSONResponse(status_code=400, content={
            "error": "Facebook App ID not configured. Set it in Config."
        })

    origin = _base_url(request)
    redirect_uri = f"{origin}/api/oauth/facebook/callback"
    state = _encode_state(org_id=org_id, origin=origin)
    auth_url = social_auth.facebook_auth_url(app_id, redirect_uri, state=state)
    return RedirectResponse(url=auth_url)


@router.get("/facebook/callback")
async def facebook_callback(request: Request, code: str = "", state: str = "",
                            error: str = ""):
    """Handle Facebook OAuth callback — exchange code, store page token."""
    if error or not code:
        log.error("Facebook OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=facebook")

    sd = _decode_state(state)
    org_id = sd.get("org_id")
    origin = sd.get("origin", "")

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

        base = origin or _base_url(request)
        redirect_uri = f"{base}/api/oauth/facebook/callback"
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
# YouTube
# ──────────────────────────────────────

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

@router.get("/youtube")
async def youtube_start(request: Request, org_id: int = 0,
                        dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Redirect user to Google/YouTube authorization page."""
    import os
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
    if not client_id:
        settings = await dl.get_all_settings()
        client_id = settings.get("youtube_client_id", "")
    if not client_id:
        return JSONResponse(status_code=400, content={
            "error": "YouTube Client ID not configured. Set YOUTUBE_CLIENT_ID env var or in settings."
        })

    origin = _base_url(request)
    redirect_uri = f"{origin}/api/oauth/youtube/callback"
    state = _encode_state(org_id=org_id, origin=origin)
    scope = " ".join(YOUTUBE_SCOPES)
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",  # force refresh_token every time
        "state": state,
    })
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return RedirectResponse(url=auth_url)


@router.get("/youtube/callback")
async def youtube_callback(request: Request, code: str = "", state: str = "",
                           error: str = ""):
    """Handle Google OAuth callback — exchange code, store YouTube refresh token."""
    if error or not code:
        log.error("YouTube OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=youtube")

    import os, httpx
    sd = _decode_state(state)
    org_id = sd.get("org_id")
    origin = sd.get("origin", "")

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        client_id = os.getenv("YOUTUBE_CLIENT_ID") or settings.get("youtube_client_id", "")
        client_secret = os.getenv("YOUTUBE_CLIENT_SECRET") or settings.get("youtube_client_secret", "")

        if not client_id or not client_secret:
            return RedirectResponse(url="/?oauth=error&provider=youtube&reason=no_credentials")

        base = origin or _base_url(request)
        redirect_uri = f"{base}/api/oauth/youtube/callback"

        # Exchange code for tokens
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "code": code,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
                tokens = resp.json()
        except Exception as e:
            log.error("YouTube token exchange failed: %s", e)
            return RedirectResponse(url="/?oauth=error&provider=youtube")

        if "error" in tokens:
            log.error("YouTube token exchange error: %s", tokens["error"])
            return RedirectResponse(url="/?oauth=error&provider=youtube")

        refresh_token = tokens.get("refresh_token", "")
        access_token = tokens.get("access_token", "")

        if not refresh_token:
            log.error("YouTube OAuth: no refresh_token in response — user may need to revoke and reconnect")
            return RedirectResponse(url="/?oauth=error&provider=youtube&reason=no_refresh_token")

        # Get channel info
        channel_title = ""
        channel_id = ""
        try:
            async with httpx.AsyncClient() as client:
                ch = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                ch_data = ch.json()
                items = ch_data.get("items", [])
                if items:
                    channel_title = items[0]["snippet"]["title"]
                    channel_id = items[0]["id"]
        except Exception as e:
            log.warning("Could not fetch YouTube channel info: %s", e)

        await dl.set_setting("youtube_refresh_token", refresh_token)
        await dl.set_setting("youtube_channel_title", channel_title)
        await dl.set_setting("youtube_channel_id", channel_id)
        await dl.commit()

        log.info("YouTube OAuth complete for org %s — channel: %s", org_id, channel_title)
        return RedirectResponse(url="/?oauth=success&provider=youtube")


# ──────────────────────────────────────
# GitHub
# ──────────────────────────────────────

GITHUB_SCOPES = "gist read:user"


@router.get("/github")
async def github_start(request: Request, org_id: int = 0, member_id: int = 0,
                       dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Redirect user to GitHub authorization page.

    If member_id is provided, stores the token on that team member
    so they can publish gists as themselves.
    """
    import os
    settings = await dl.get_all_settings()
    client_id = settings.get("github_oauth_client_id", "") or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
    if not client_id:
        async with async_session() as session:
            global_dl = DataLayer(session, org_id=None)
            gs = await global_dl.get_all_settings()
            client_id = gs.get("github_oauth_client_id", "") or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
    if not client_id:
        return JSONResponse(status_code=400, content={
            "error": "GitHub OAuth Client ID not configured. Add GITHUB_OAUTH_CLIENT_ID to settings or env."
        })

    origin = _base_url(request)
    redirect_uri = f"{origin}/api/oauth/github/callback"
    state = _encode_state(org_id=org_id, member_id=member_id, origin=origin)
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": GITHUB_SCOPES,
        "state": state,
    })
    auth_url = f"https://github.com/login/oauth/authorize?{params}"
    return RedirectResponse(url=auth_url)


@router.get("/github/callback")
async def github_callback(request: Request, code: str = "", state: str = "",
                          error: str = ""):
    """Handle GitHub OAuth callback — exchange code, store token."""
    if error or not code:
        log.error("GitHub OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=github")

    import os
    sd = _decode_state(state)
    org_id = sd.get("org_id")
    member_id = sd.get("member_id")
    origin = sd.get("origin", "")

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        settings = await dl.get_all_settings()

        client_id = settings.get("github_oauth_client_id", "") or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
        client_secret = settings.get("github_oauth_client_secret", "") or os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            # Try global settings
            global_dl = DataLayer(session, org_id=None)
            gs = await global_dl.get_all_settings()
            client_id = client_id or gs.get("github_oauth_client_id", "") or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
            client_secret = client_secret or gs.get("github_oauth_client_secret", "") or os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            return RedirectResponse(url="/?oauth=error&provider=github&reason=no_credentials")

        base = origin or _base_url(request)
        redirect_uri = f"{base}/api/oauth/github/callback"

        # Exchange code for token
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://github.com/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
                tokens = resp.json()
        except Exception as e:
            log.error("GitHub token exchange failed: %s", e)
            return RedirectResponse(url="/?oauth=error&provider=github")

        if "error" in tokens or not tokens.get("access_token"):
            log.error("GitHub token exchange error: %s", tokens)
            return RedirectResponse(url="/?oauth=error&provider=github")

        access_token = tokens["access_token"]

        # Fetch GitHub user info
        github_login = ""
        github_name = ""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                user_resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                if user_resp.status_code == 200:
                    user_data = user_resp.json()
                    github_login = user_data.get("login", "")
                    github_name = user_data.get("name", "") or github_login
        except Exception as e:
            log.warning("GitHub user fetch failed: %s", e)

        if member_id:
            # Store on the specific team member
            from sqlalchemy import update
            from models import TeamMember
            update_vals = {"github_access_token": access_token}
            if github_login:
                update_vals["github_username"] = github_login
            await session.execute(
                update(TeamMember)
                .where(TeamMember.id == member_id)
                .values(**update_vals)
            )
            await session.commit()
            log.info("GitHub OAuth complete for member %s — login: %s", member_id, github_login)
            return RedirectResponse(url=f"/?oauth=success&provider=github&for=member&name={github_name}")
        else:
            # Store at org level as a PAT for API calls
            await dl.set_setting("github_token", access_token)
            if github_login:
                await dl.set_setting("github_login", github_login)
            await dl.commit()
            log.info("GitHub OAuth complete for org %s — login: %s", org_id, github_login)
            return RedirectResponse(url=f"/?oauth=success&provider=github&name={github_name}")


# ──────────────────────────────────────
# Connection status
# ──────────────────────────────────────

@router.get("/status")
async def oauth_status(dl: DataLayer = Depends(get_authenticated_data_layer),
                       auth_info: dict | None = Depends(resolve_token)):
    """Check which social accounts are connected for this user/org."""
    settings = await dl.get_all_settings()

    # Also pull global settings for app credentials
    global_settings = {}
    if dl.org_id:
        async with async_session() as session:
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()

    all_settings = {**global_settings, **settings}

    # LinkedIn: read from user's profile (account-level), not org settings
    li_token = ""
    li_profile_name = ""
    li_expires_ts = 0
    user_id = auth_info.get("user_id") if auth_info else None
    if user_id:
        async with async_session() as session:
            from sqlalchemy import select as sa_select
            from models import Profile
            result = await session.execute(
                sa_select(Profile).where(Profile.id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                li_token = profile.linkedin_access_token or ""
                li_profile_name = profile.linkedin_profile_name or ""
                li_expires_ts = profile.linkedin_token_expires_at or 0

    li_healthy = li_expires_ts > int(time.time()) + 3600 if li_expires_ts else False
    li_days_left = max(0, (li_expires_ts - int(time.time())) // 86400) if li_expires_ts else 0

    return {
        "linkedin": {
            "app_configured": bool(all_settings.get("linkedin_client_id") or app_cfg.linkedin_client_id),
            "connected": bool(li_token),
            "profile_name": li_profile_name,
            "token_healthy": li_healthy,
            "days_remaining": li_days_left,
        },
        "facebook": {
            "app_configured": bool(all_settings.get("facebook_app_id")),
            "connected": bool(settings.get("facebook_page_token")),
            "page_name": settings.get("facebook_page_name", ""),
        },
        "youtube": {
            "connected": bool(settings.get("youtube_refresh_token")),
            "channel_title": settings.get("youtube_channel_title", ""),
            "channel_id": settings.get("youtube_channel_id", ""),
        },
        "github": {
            "app_configured": bool(all_settings.get("github_oauth_client_id")),
            "connected": bool(settings.get("github_token")),
            "login": settings.get("github_login", ""),
        },
    }
