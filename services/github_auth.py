"""GitHub App authentication.

Generates installation tokens so all GitHub API calls go out as the
Pressroom bot identity rather than a personal access token.

Flow:
  1. Sign a JWT with the App's private key (valid 10 min)
  2. List installations to find the right installation ID
  3. Exchange JWT for an installation access token (valid 1 hour)
  4. Cache the token until 5 min before expiry

If App credentials aren't configured, falls back to settings.github_token
(personal token) so local dev still works without the .pem file.
"""

import time
import logging
import httpx

from config import settings

log = logging.getLogger("pressroom")

# Simple in-process cache: {installation_id: (token, expires_at)}
_token_cache: dict[int, tuple[str, float]] = {}
_app_installation_id: int | None = None


def _make_jwt() -> str:
    """Sign a GitHub App JWT. Requires PyJWT."""
    import jwt  # PyJWT

    app_id = settings.github_app_id
    private_key = settings.github_app_private_key

    if not app_id or not private_key:
        raise ValueError("GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY not configured")

    # GitHub requires RS256, iat slightly in the past to allow clock skew
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _get_installation_id(jwt_token: str) -> int:
    """Fetch the first installation ID for this app."""
    global _app_installation_id
    if _app_installation_id:
        return _app_installation_id

    async with httpx.AsyncClient() as c:
        r = await c.get(
            "https://api.github.com/app/installations",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        installations = r.json()
        if not installations:
            raise ValueError("Pressroom GitHub App has no installations")
        _app_installation_id = installations[0]["id"]
        return _app_installation_id


async def _get_installation_token(installation_id: int, jwt_token: str) -> tuple[str, float]:
    """Exchange JWT for an installation access token."""
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        data = r.json()
        token = data["token"]
        # expires_at is ISO8601 — convert to unix timestamp
        from datetime import datetime, timezone
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        expires_ts = expires_at.timestamp()
        return token, expires_ts


async def get_github_token() -> str:
    """Return a valid GitHub token for API calls.

    Uses GitHub App installation token if configured, falls back to
    personal access token (settings.github_token) for local dev.
    """
    if not settings.github_app_id or not settings.github_app_private_key:
        # Local dev fallback
        return settings.github_token

    global _token_cache, _app_installation_id

    try:
        jwt_token = _make_jwt()
        installation_id = await _get_installation_id(jwt_token)

        # Check cache — refresh 5 min before expiry
        cached = _token_cache.get(installation_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at - 300:
                return token

        token, expires_at = await _get_installation_token(installation_id, jwt_token)
        _token_cache[installation_id] = (token, expires_at)
        log.debug("GitHub App token refreshed, expires in %.0f min", (expires_at - time.time()) / 60)
        return token

    except Exception as e:
        log.warning("GitHub App auth failed, falling back to personal token: %s", e)
        return settings.github_token


def get_github_headers(token: str) -> dict:
    """Standard headers for GitHub API calls."""
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h
