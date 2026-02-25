"""Settings endpoints — configure API keys, scout sources, voice profile.

All settings are org-scoped via the X-Org-Id header.
Global settings (no org) are used for shared config like API keys.
"""

import json
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Default settings structure
DEFAULTS = {
    # API Keys (typically global, but can be per-org)
    "anthropic_api_key": "",
    "github_token": "",
    # DreamFactory
    "df_base_url": "http://localhost:8080",
    "df_api_key": "",
    # Scout sources
    "scout_github_orgs": '[]',
    "scout_github_repos": '["dreamfactorysoftware/dreamfactory"]',
    "scout_hn_keywords": '["DreamFactory", "REST API", "API gateway"]',
    "scout_subreddits": '["selfhosted", "webdev"]',
    "scout_rss_feeds": '[]',
    "scout_web_queries": '[]',
    "scout_google_news_keywords": '[]',
    "scout_devto_tags": '[]',
    "scout_producthunt_enabled": '',
    # Voice profile — core
    "golden_anchor": "",
    "voice_persona": "",
    "voice_audience": "",
    "voice_tone": "",
    "voice_never_say": '[]',
    "voice_always": "",
    "voice_brand_keywords": '[]',
    "voice_writing_examples": "",
    "voice_bio": "",
    # Voice profile — per-channel overrides
    "voice_linkedin_style": "",
    "voice_x_style": "",
    "voice_blog_style": "",
    "voice_email_style": "",
    "voice_newsletter_style": "",
    "voice_yt_style": "",
    # Engine
    "claude_model": "claude-sonnet-4-6",
    "claude_model_fast": "claude-haiku-4-5-20251001",
    # Social OAuth (app credentials — typically global)
    "linkedin_client_id": "",
    "linkedin_client_secret": "",
    "facebook_app_id": "",
    "facebook_app_secret": "",
    # Social OAuth (per-org tokens — set by OAuth callback)
    "linkedin_access_token": "",
    "linkedin_author_urn": "",
    "linkedin_profile_name": "",
    "facebook_page_token": "",
    "facebook_page_id": "",
    "facebook_page_name": "",
    # Webhook
    "github_webhook_secret": "",
    # Per-org API key assignment (references api_keys.id)
    "anthropic_api_key_id": "",
    # Onboarding metadata
    "onboard_company_name": "",
    "onboard_company_description": "",
    "onboard_domain": "",
    "onboard_industry": "",
    "onboard_topics": "[]",
    "onboard_competitors": "[]",
    "onboard_complete": "",
    "social_profiles": "{}",
    "company_properties": "{}",
    "df_service_map": "",
    # Dev.to
    "devto_api_key": "",
    # Slack notifications
    "slack_webhook_url": "",
    "slack_notify_on_generate": "",
    "slack_channel_name": "",
    # Publish actions — per-channel behavior (JSON: {"linkedin": "auto", ...})
    "publish_actions": "{}",
    # Saved ideas (JSON array, per-org)
    "saved_ideas": "[]",
}

# Account-level keys — shared across all companies, saved with org_id=NULL
ACCOUNT_KEYS = {
    "anthropic_api_key", "github_token",
    "df_base_url", "df_api_key",
    "claude_model", "claude_model_fast",
    "linkedin_client_id", "linkedin_client_secret",
    "facebook_app_id", "facebook_app_secret",
    "github_webhook_secret",
}

# Keys that should be masked in GET responses
SENSITIVE_KEYS = {
    "anthropic_api_key", "github_token", "df_api_key", "github_webhook_secret",
    "linkedin_client_secret", "facebook_app_secret",
    "linkedin_access_token", "facebook_page_token",
    "slack_webhook_url", "devto_api_key",
}


def _mask(key: str, value: str) -> str:
    if key in SENSITIVE_KEYS and value:
        return value[:8] + "..." if len(value) > 8 else "***"
    return value


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


@router.get("")
async def get_settings(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get all settings (sensitive values masked). Merges account + org settings."""
    stored = await dl.get_all_settings()

    merged = {}
    for key, default in DEFAULTS.items():
        raw = stored.get(key, default)
        merged[key] = {
            "value": _mask(key, raw),
            "is_set": bool(raw and raw != default),
            "sensitive": key in SENSITIVE_KEYS,
            "scope": "account" if key in ACCOUNT_KEYS else "company",
        }
    return merged


@router.get("/raw/{key}")
async def get_setting_raw(key: str, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get a single setting value (unmasked). Use sparingly."""
    value = await dl.get_setting(key)
    return {"key": key, "value": value or DEFAULTS.get(key, "")}


@router.put("")
async def update_settings(req: SettingsUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update one or more settings. Account keys route to org_id=NULL, company keys to current org."""
    updated = []
    rejected = []
    for key, value in req.settings.items():
        if key not in DEFAULTS:
            rejected.append(key)
            continue
        if key in ACCOUNT_KEYS:
            await dl.set_account_setting(key, value)
        else:
            await dl.set_setting(key, value)
        updated.append(key)

    await dl.commit()

    # Reload runtime config from DB
    await _sync_to_runtime(dl)

    return {"updated": updated, "rejected": rejected}


@router.get("/status")
async def connection_status(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Check connection status for all configured services. Uses merged account + org settings."""
    stored = await dl.get_all_settings()

    status = {}

    # Anthropic
    api_key = stored.get("anthropic_api_key", "")
    status["anthropic"] = {
        "configured": bool(api_key),
        "model": stored.get("claude_model", DEFAULTS["claude_model"]),
    }

    # GitHub
    gh_token = stored.get("github_token", "")
    if gh_token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={"Authorization": f"token {gh_token}"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    user = resp.json()
                    status["github"] = {"configured": True, "connected": True, "user": user.get("login", "")}
                else:
                    status["github"] = {"configured": True, "connected": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            status["github"] = {"configured": True, "connected": False, "error": str(e)}
    else:
        status["github"] = {"configured": False}

    # DreamFactory
    df_url = stored.get("df_base_url", DEFAULTS["df_base_url"])
    df_key = stored.get("df_api_key", "")
    if df_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{df_url}/api/v2/system/environment",
                    headers={"X-DreamFactory-Api-Key": df_key},
                    timeout=5,
                )
                status["dreamfactory"] = {
                    "configured": True,
                    "connected": resp.status_code == 200,
                    "url": df_url,
                }
        except Exception as e:
            status["dreamfactory"] = {"configured": True, "connected": False, "url": df_url, "error": str(e)}
    else:
        status["dreamfactory"] = {"configured": False, "url": df_url}

    # Scout sources
    repos = json.loads(stored.get("scout_github_repos", DEFAULTS["scout_github_repos"]))
    hn_kw = json.loads(stored.get("scout_hn_keywords", DEFAULTS["scout_hn_keywords"]))
    subs = json.loads(stored.get("scout_subreddits", DEFAULTS["scout_subreddits"]))
    rss = json.loads(stored.get("scout_rss_feeds", DEFAULTS["scout_rss_feeds"]))
    status["scout"] = {
        "github_repos": len(repos),
        "hn_keywords": len(hn_kw),
        "subreddits": len(subs),
        "rss_feeds": len(rss),
        "total_sources": len(repos) + len(subs) + len(rss) + (1 if hn_kw else 0),
    }

    return status


@router.get("/df-services")
async def df_services():
    """Discover DF services — databases, social platforms, etc."""
    from services.df_client import df
    if not df.available:
        return {"available": False, "services": [], "social": [], "databases": []}
    try:
        all_services = await df.list_services()
        social = await df.discover_social_services()
        databases = await df.discover_db_services()

        social_with_auth = []
        for svc in social:
            name = svc.get("name", "")
            try:
                auth = await df.social_auth_status(name)
                svc["auth_status"] = auth
            except Exception:
                svc["auth_status"] = {"connected": False}
            social_with_auth.append(svc)

        return {
            "available": True,
            "services": all_services,
            "social": social_with_auth,
            "databases": databases,
        }
    except Exception as e:
        return {"available": False, "error": str(e), "services": [], "social": [], "databases": []}


# ── API Key Management ──

class ApiKeyCreate(BaseModel):
    label: str
    key_value: str

class ApiKeyUpdateLabel(BaseModel):
    label: str

@router.get("/api-keys/status")
async def api_key_status(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Check if any API key is available (env or stored). Frontend uses this to skip key entry."""
    key = await dl.resolve_api_key()
    return {"available": bool(key)}

@router.get("/api-keys")
async def list_api_keys(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List all labeled API keys (values masked)."""
    return await dl.list_api_keys()

@router.post("/api-keys")
async def create_api_key(req: ApiKeyCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    result = await dl.create_api_key(req.label, req.key_value)
    await dl.commit()
    return result

@router.put("/api-keys/{key_id}")
async def update_api_key(key_id: int, req: ApiKeyUpdateLabel, dl: DataLayer = Depends(get_authenticated_data_layer)):
    result = await dl.update_api_key_label(key_id, req.label)
    if not result:
        return {"error": "Key not found"}
    await dl.commit()
    return result

@router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    deleted = await dl.delete_api_key(key_id)
    if not deleted:
        return {"error": "Key not found"}
    await dl.commit()
    return {"deleted": key_id}


# ── API Token Management (auth tokens for the Pressroom API) ──

class TokenCreate(BaseModel):
    org_id: int
    label: str = "default"

@router.get("/api-tokens")
async def list_api_tokens(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """List all API tokens (token values masked except first 8 chars)."""
    from sqlalchemy import select
    from models import ApiToken
    result = await dl.db.execute(select(ApiToken).where(ApiToken.revoked == False))
    tokens = result.scalars().all()
    return [
        {
            "id": t.id,
            "org_id": t.org_id,
            "label": t.label,
            "token_preview": t.token[:11] + "...",
            "created_at": str(t.created_at),
            "last_used_at": str(t.last_used_at) if t.last_used_at else None,
        }
        for t in tokens
    ]

@router.post("/api-tokens")
async def create_api_token(req: TokenCreate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Create a new API token for an org. Returns the full token value (only shown once)."""
    from api.auth import create_token
    token = await create_token(dl.db, req.org_id, req.label)
    return {
        "id": token.id,
        "org_id": token.org_id,
        "label": token.label,
        "token": token.token,
        "created_at": str(token.created_at),
    }

@router.delete("/api-tokens/{token_id}")
async def revoke_api_token(token_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Revoke an API token."""
    from sqlalchemy import update
    from models import ApiToken
    result = await dl.db.execute(
        update(ApiToken).where(ApiToken.id == token_id).values(revoked=True)
    )
    await dl.db.commit()
    if result.rowcount == 0:
        return {"error": "Token not found"}
    return {"revoked": token_id}


async def _sync_to_runtime(dl: DataLayer):
    """Push account-level DB settings into the runtime config object."""
    from config import settings as cfg
    stored = await dl.get_account_settings()

    if stored.get("anthropic_api_key"):
        cfg.anthropic_api_key = stored["anthropic_api_key"]
    if stored.get("github_token"):
        cfg.github_token = stored["github_token"]
    if stored.get("df_base_url"):
        cfg.df_base_url = stored["df_base_url"]
    if stored.get("df_api_key"):
        cfg.df_api_key = stored["df_api_key"]
    if stored.get("claude_model"):
        cfg.claude_model = stored["claude_model"]
    if stored.get("claude_model_fast"):
        cfg.claude_model_fast = stored["claude_model_fast"]
    if stored.get("github_webhook_secret"):
        cfg.github_webhook_secret = stored["github_webhook_secret"]

    try:
        if stored.get("scout_github_repos"):
            cfg.scout_github_repos = json.loads(stored["scout_github_repos"])
        if stored.get("scout_hn_keywords"):
            cfg.scout_hn_keywords = json.loads(stored["scout_hn_keywords"])
        if stored.get("scout_subreddits"):
            cfg.scout_subreddits = json.loads(stored["scout_subreddits"])
        if stored.get("scout_rss_feeds"):
            cfg.scout_rss_feeds = json.loads(stored["scout_rss_feeds"])
    except json.JSONDecodeError:
        pass
