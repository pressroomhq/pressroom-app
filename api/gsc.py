"""Google Search Console integration — OAuth flow, analytics data, URL inspection.

Flow:
  1. Frontend calls GET /api/gsc/auth?org_id=N
  2. We redirect to Google's OAuth consent screen
  3. Google redirects back to GET /api/gsc/auth/callback?code=...&state=...
  4. We exchange code for access+refresh tokens, store per-org, redirect to frontend
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel

from database import get_data_layer, async_session
from services.data_layer import DataLayer
from services.gsc_client import (
    google_auth_url, exchange_code, refresh_access_token, service_account_access_token, GSCClient,
)

log = logging.getLogger("pressroom.gsc")

router = APIRouter(prefix="/api/gsc", tags=["gsc"])


def _base_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{scheme}://{host}"


async def _get_credentials(dl: DataLayer) -> dict:
    """Load Google OAuth app credentials (global or org-level)."""
    settings = await dl.get_all_settings()
    client_id = settings.get("google_client_id", "")
    client_secret = settings.get("google_client_secret", "")

    if not client_id:
        async with async_session() as session:
            global_dl = DataLayer(session, org_id=None)
            global_settings = await global_dl.get_all_settings()
            client_id = client_id or global_settings.get("google_client_id", "")
            client_secret = client_secret or global_settings.get("google_client_secret", "")

    return {"client_id": client_id, "client_secret": client_secret}


async def _get_client(dl: DataLayer) -> GSCClient | None:
    """Build a GSCClient with a valid access token.

    Tries service account auth first, falls back to OAuth refresh token flow.
    Service account tokens are short-lived (1h) and minted fresh each time if expired.
    """
    settings = await dl.get_all_settings()

    # ── Service account path ──────────────────────────────────────────────
    sa_json_raw = settings.get("gsc_service_account_json", "")
    if sa_json_raw:
        try:
            sa_json = json.loads(sa_json_raw)
        except (json.JSONDecodeError, TypeError):
            sa_json = None

        if sa_json:
            # Reuse cached token if still valid (>5 min remaining)
            access_token = settings.get("gsc_access_token", "")
            expires_at = settings.get("gsc_token_expires_at", "")
            expires_ts = int(expires_at) if expires_at.isdigit() else 0

            if access_token and expires_ts > int(time.time()) + 300:
                return GSCClient(access_token)

            # Mint a new token
            result = await service_account_access_token(sa_json)
            if "error" in result:
                log.error("GSC service account token error: %s", result["error"])
                return None
            access_token = result["access_token"]
            new_expires = int(time.time()) + int(result.get("expires_in", 3600))
            await dl.set_setting("gsc_access_token", access_token)
            await dl.set_setting("gsc_token_expires_at", str(new_expires))
            await dl.commit()
            log.info("GSC service account token minted")
            return GSCClient(access_token)

    # ── OAuth path ────────────────────────────────────────────────────────
    access_token = settings.get("gsc_access_token", "")
    refresh_token = settings.get("gsc_refresh_token", "")
    expires_at = settings.get("gsc_token_expires_at", "")

    if not access_token and not refresh_token:
        return None

    # Refresh if expired or expiring within 5 minutes
    expires_ts = int(expires_at) if expires_at.isdigit() else 0
    if expires_ts and expires_ts < int(time.time()) + 300 and refresh_token:
        creds = await _get_credentials(dl)
        if creds["client_id"] and creds["client_secret"]:
            result = await refresh_access_token(
                creds["client_id"], creds["client_secret"], refresh_token
            )
            if "access_token" in result:
                access_token = result["access_token"]
                new_expires = int(time.time()) + int(result.get("expires_in", 3600))
                await dl.set_setting("gsc_access_token", access_token)
                await dl.set_setting("gsc_token_expires_at", str(new_expires))
                await dl.commit()
                log.info("GSC access token refreshed")
            else:
                log.warning("GSC token refresh failed: %s", result.get("error"))
                return None

    if not access_token:
        return None

    return GSCClient(access_token)


# ──────────────────────────────────────
# Service Account
# ──────────────────────────────────────

class ServiceAccountRequest(BaseModel):
    service_account_json: str  # raw JSON string from the key file


@router.post("/service-account")
async def save_service_account(req: ServiceAccountRequest, dl: DataLayer = Depends(get_data_layer)):
    """Save a service account key and immediately verify it by minting a token."""
    try:
        sa = json.loads(req.service_account_json)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    if sa.get("type") != "service_account":
        return JSONResponse(status_code=400, content={
            "error": "Not a service account key — expected type: service_account"
        })

    required = ("client_email", "private_key", "token_uri")
    missing = [k for k in required if not sa.get(k)]
    if missing:
        return JSONResponse(status_code=400, content={
            "error": f"Service account JSON missing fields: {', '.join(missing)}"
        })

    # Test it immediately — mint a token
    result = await service_account_access_token(sa)
    if "error" in result:
        return JSONResponse(status_code=400, content={
            "error": f"Token mint failed: {result['error']}"
        })

    # Store the key and cache the token
    await dl.set_setting("gsc_service_account_json", req.service_account_json)
    await dl.set_setting("gsc_access_token", result["access_token"])
    new_expires = int(time.time()) + int(result.get("expires_in", 3600))
    await dl.set_setting("gsc_token_expires_at", str(new_expires))
    # Clear any old OAuth tokens — one auth mode at a time
    await dl.set_setting("gsc_refresh_token", "")
    await dl.commit()

    # Fetch properties so we can auto-set the first one
    client = GSCClient(result["access_token"])
    sites = await client.list_sites()
    if sites:
        await dl.set_setting("gsc_property", sites[0].get("siteUrl", ""))
        await dl.commit()

    log.info("GSC service account saved for %s — %d properties", sa["client_email"], len(sites))
    return {
        "saved": True,
        "client_email": sa["client_email"],
        "properties": len(sites),
        "first_property": sites[0].get("siteUrl", "") if sites else "",
    }


# ──────────────────────────────────────
# OAuth
# ──────────────────────────────────────

@router.get("/auth")
async def gsc_auth_start(request: Request, org_id: int = 0,
                         dl: DataLayer = Depends(get_data_layer)):
    """Redirect user to Google OAuth consent screen for GSC access."""
    creds = await _get_credentials(dl)
    if not creds["client_id"]:
        return JSONResponse(status_code=400, content={
            "error": "Google Client ID not configured. Set google_client_id / google_client_secret in Settings."
        })

    redirect_uri = f"{_base_url(request)}/api/gsc/auth/callback"
    state = str(org_id)
    url = google_auth_url(creds["client_id"], redirect_uri, state=state)
    return RedirectResponse(url=url)


@router.get("/auth/callback")
async def gsc_auth_callback(request: Request, code: str = "", state: str = "",
                            error: str = ""):
    """Handle Google OAuth callback — exchange code, store tokens."""
    if error or not code:
        log.error("Google OAuth error: %s", error or "no code returned")
        return RedirectResponse(url="/?oauth=error&provider=gsc")

    org_id = int(state) if state.isdigit() else None

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        creds = await _get_credentials(dl)

        if not creds["client_id"] or not creds["client_secret"]:
            return RedirectResponse(url="/?oauth=error&provider=gsc&reason=no_credentials")

        redirect_uri = f"{_base_url(request)}/api/gsc/auth/callback"
        result = await exchange_code(
            creds["client_id"], creds["client_secret"], code, redirect_uri
        )

        if "error" in result:
            log.error("Google token exchange failed: %s", result["error"])
            return RedirectResponse(url="/?oauth=error&provider=gsc")

        # Store tokens per-org
        await dl.set_setting("gsc_access_token", result.get("access_token", ""))
        if result.get("refresh_token"):
            await dl.set_setting("gsc_refresh_token", result["refresh_token"])
        expires_in = result.get("expires_in", 3600)
        await dl.set_setting("gsc_token_expires_at", str(int(time.time()) + int(expires_in)))
        await dl.set_setting("gsc_connected_at", str(int(time.time())))

        # Fetch and store the list of properties so we remember what they have access to
        client = GSCClient(result["access_token"])
        sites = await client.list_sites()
        if sites:
            # Store first property URL as the default
            await dl.set_setting("gsc_property", sites[0].get("siteUrl", ""))

        await dl.commit()

        log.info("GSC OAuth complete for org %s — %d properties found", org_id, len(sites))
        return RedirectResponse(url="/?oauth=success&provider=gsc")


# ──────────────────────────────────────
# Status + disconnect
# ──────────────────────────────────────

@router.get("/status")
async def gsc_status(dl: DataLayer = Depends(get_data_layer)):
    """Check whether GSC is connected and token is valid."""
    settings = await dl.get_all_settings()
    creds = await _get_credentials(dl)

    sa_json_raw = settings.get("gsc_service_account_json", "")
    using_service_account = bool(sa_json_raw)

    connected = bool(
        using_service_account
        or settings.get("gsc_access_token")
        or settings.get("gsc_refresh_token")
    )
    property_url = settings.get("gsc_property", "")

    # Token health: service accounts self-refresh, so always healthy if configured
    expires_at = settings.get("gsc_token_expires_at", "")
    expires_ts = int(expires_at) if expires_at.isdigit() else 0
    has_refresh = bool(settings.get("gsc_refresh_token"))
    token_healthy = using_service_account or has_refresh or (expires_ts > int(time.time()) + 300)

    # Extract service account email for display
    sa_email = ""
    if sa_json_raw:
        try:
            sa_email = json.loads(sa_json_raw).get("client_email", "")
        except Exception:
            pass

    return {
        "app_configured": bool(creds["client_id"]) or using_service_account,
        "connected": connected,
        "property": property_url,
        "token_healthy": token_healthy if connected else False,
        "has_refresh_token": has_refresh,
        "auth_mode": "service_account" if using_service_account else "oauth",
        "service_account_email": sa_email,
    }


@router.delete("/disconnect")
async def gsc_disconnect(dl: DataLayer = Depends(get_data_layer)):
    """Remove GSC tokens, service account key, and property."""
    for key in ("gsc_access_token", "gsc_refresh_token", "gsc_token_expires_at",
                "gsc_connected_at", "gsc_property", "gsc_service_account_json"):
        await dl.set_setting(key, "")
    await dl.commit()
    log.info("GSC disconnected")
    return {"disconnected": True}


# ──────────────────────────────────────
# Data endpoints
# ──────────────────────────────────────

@router.get("/properties")
async def gsc_properties(dl: DataLayer = Depends(get_data_layer)):
    """List all Search Console properties the user has access to."""
    client = await _get_client(dl)
    if not client:
        return {"error": "GSC not connected"}

    sites = await client.list_sites()
    return {"properties": sites, "count": len(sites)}


class SetPropertyRequest(BaseModel):
    property_url: str


@router.put("/property")
async def set_property(req: SetPropertyRequest, dl: DataLayer = Depends(get_data_layer)):
    """Set the active GSC property for this org."""
    await dl.set_setting("gsc_property", req.property_url)
    await dl.commit()
    return {"property": req.property_url}


@router.get("/analytics")
async def gsc_analytics(
    days: int = Query(28, ge=1, le=90),
    dimension: str = Query("query"),
    limit: int = Query(25, ge=1, le=1000),
    dl: DataLayer = Depends(get_data_layer),
):
    """Fetch search analytics data (queries, pages, countries, devices)."""
    client = await _get_client(dl)
    if not client:
        return {"error": "GSC not connected"}

    property_url = await dl.get_setting("gsc_property")
    if not property_url:
        return {"error": "No GSC property selected"}

    valid_dimensions = {"query", "page", "country", "device", "date"}
    dims = [d.strip() for d in dimension.split(",") if d.strip() in valid_dimensions]
    if not dims:
        dims = ["query"]

    result = await client.search_analytics(property_url, days=days,
                                           dimensions=dims, row_limit=limit)
    return result


@router.get("/sitemaps")
async def gsc_sitemaps(dl: DataLayer = Depends(get_data_layer)):
    """List sitemaps submitted for the active property."""
    client = await _get_client(dl)
    if not client:
        return {"error": "GSC not connected"}

    property_url = await dl.get_setting("gsc_property")
    if not property_url:
        return {"error": "No GSC property selected"}

    sitemaps = await client.list_sitemaps(property_url)
    return {"sitemaps": sitemaps, "count": len(sitemaps)}


class InspectRequest(BaseModel):
    url: str


@router.post("/inspect")
async def gsc_inspect(req: InspectRequest, dl: DataLayer = Depends(get_data_layer)):
    """Inspect a URL's indexing status."""
    client = await _get_client(dl)
    if not client:
        return {"error": "GSC not connected"}

    property_url = await dl.get_setting("gsc_property")
    if not property_url:
        return {"error": "No GSC property selected"}

    result = await client.inspect_url(property_url, req.url)
    return result


@router.get("/summary")
async def gsc_summary(dl: DataLayer = Depends(get_data_layer)):
    """Top-line GSC performance summary for the active property.

    Returns: total clicks, impressions, avg CTR, avg position over 28 days,
    plus top 5 queries and top 5 pages by clicks.
    """
    client = await _get_client(dl)
    if not client:
        return {"connected": False}

    property_url = await dl.get_setting("gsc_property")
    if not property_url:
        return {"connected": True, "error": "No GSC property selected"}

    # Fetch top queries and top pages in parallel
    queries_data, pages_data = await asyncio.gather(
        client.search_analytics(property_url, days=28, dimensions=["query"], row_limit=10),
        client.search_analytics(property_url, days=28, dimensions=["page"], row_limit=10),
    )

    def _row(r):
        return {
            "key": r.get("keys", [""])[0],
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": round(r.get("ctr", 0) * 100, 1),
            "position": round(r.get("position", 0), 1),
        }

    q_rows = [_row(r) for r in queries_data.get("rows", [])]
    p_rows = [_row(r) for r in pages_data.get("rows", [])]

    # Aggregate totals from query rows
    total_clicks = sum(r["clicks"] for r in q_rows)
    total_impressions = sum(r["impressions"] for r in q_rows)
    avg_ctr = round(total_clicks / total_impressions * 100, 1) if total_impressions else 0
    avg_position = round(sum(r["position"] for r in q_rows) / len(q_rows), 1) if q_rows else 0

    return {
        "connected": True,
        "property": property_url,
        "period_days": 28,
        "totals": {
            "clicks": total_clicks,
            "impressions": total_impressions,
            "ctr": avg_ctr,
            "position": avg_position,
        },
        "top_queries": q_rows[:5],
        "top_pages": p_rows[:5],
    }
