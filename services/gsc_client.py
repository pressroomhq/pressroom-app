"""Google Search Console API client.

Wraps the GSC REST API using httpx, consistent with how
the rest of Pressroom handles external service calls.

Supports two auth modes:
  - OAuth 2.0 (user flow): client_id + client_secret → access/refresh tokens
  - Service Account: private_key JWT assertion → short-lived access token
    Requires the service account email to be added as a GSC property user.
"""

import base64
import json
import logging
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("pressroom.gsc")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API = "https://www.googleapis.com/webmasters/v3"
SEARCH_CONSOLE_API = "https://searchconsole.googleapis.com/v1"

SCOPES = "https://www.googleapis.com/auth/webmasters.readonly"


def google_auth_url(client_id: str, redirect_uri: str, state: str = "") -> str:
    """Build the Google OAuth authorization URL for GSC access."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{qs}"


async def exchange_code(client_id: str, client_secret: str,
                        code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(GOOGLE_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        })
        if resp.status_code != 200:
            log.error("Google token exchange failed: %s %s", resp.status_code, resp.text)
            return {"error": f"Token exchange failed: {resp.status_code}"}
        return resp.json()


async def refresh_access_token(client_id: str, client_secret: str,
                               refresh_token: str) -> dict:
    """Use refresh token to get a new access token."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(GOOGLE_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        })
        if resp.status_code != 200:
            log.error("Google token refresh failed: %s %s", resp.status_code, resp.text)
            return {"error": f"Token refresh failed: {resp.status_code}"}
        return resp.json()


async def service_account_access_token(service_account_json: dict) -> dict:
    """Exchange a service account key for a short-lived access token via JWT assertion.

    The service account email must be added as a user in GSC for the property.
    Returns dict with 'access_token' and 'expires_in', or 'error'.
    """
    try:
        import struct
        import hmac
        import hashlib

        client_email = service_account_json.get("client_email", "")
        private_key_pem = service_account_json.get("private_key", "")
        token_uri = service_account_json.get("token_uri", GOOGLE_TOKEN_URL)

        if not client_email or not private_key_pem:
            return {"error": "service_account_json missing client_email or private_key"}

        # Build JWT header + claims
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": client_email,
            "scope": SCOPES,
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
        claims_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
        signing_input = f"{header_b64}.{claims_b64}".encode()

        # Sign with RSA private key using stdlib only (via cryptography if available,
        # else fall back to trying google-auth)
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(), password=None
            )
            signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        except ImportError:
            # Try google-auth as fallback
            try:
                import google.auth.crypt
                signer = google.auth.crypt.RSASigner.from_service_account_info(service_account_json)
                signature = signer.sign(signing_input)
            except ImportError:
                return {"error": "cryptography package required: pip install cryptography"}

        jwt_token = f"{header_b64}.{claims_b64}.{_b64url(signature)}"

        # Exchange JWT for access token
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(token_uri, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt_token,
            })
            if resp.status_code != 200:
                log.error("Service account token exchange failed: %s %s", resp.status_code, resp.text)
                return {"error": f"Token exchange failed: {resp.status_code} — {resp.text[:200]}"}
            return resp.json()

    except Exception as e:
        log.exception("service_account_access_token error")
        return {"error": str(e)}


class GSCClient:
    """Thin wrapper around the Google Search Console REST API."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def list_sites(self) -> list[dict]:
        """List all Search Console properties the user has access to."""
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(f"{GSC_API}/sites", headers=self._headers)
            if resp.status_code != 200:
                log.error("GSC list_sites failed: %s", resp.status_code)
                return []
            data = resp.json()
            return data.get("siteEntry", [])

    async def search_analytics(self, site_url: str, days: int = 28,
                               dimensions: list[str] | None = None,
                               row_limit: int = 25) -> dict:
        """Query search analytics (clicks, impressions, CTR, position)."""
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=days)

        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions or ["query"],
            "rowLimit": row_limit,
        }

        encoded = quote(site_url, safe="")
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                f"{GSC_API}/sites/{encoded}/searchAnalytics/query",
                headers=self._headers,
                json=body,
            )
            if resp.status_code != 200:
                log.error("GSC search_analytics failed: %s %s", resp.status_code, resp.text[:300])
                return {"error": f"API error: {resp.status_code}"}
            return resp.json()

    async def list_sitemaps(self, site_url: str) -> list[dict]:
        """List sitemaps submitted for a property."""
        encoded = quote(site_url, safe="")
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                f"{GSC_API}/sites/{encoded}/sitemaps",
                headers=self._headers,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("sitemap", [])

    async def inspect_url(self, site_url: str, inspect_url: str) -> dict:
        """Inspect a URL's index status."""
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                f"{SEARCH_CONSOLE_API}/urlInspection/index:inspect",
                headers=self._headers,
                json={
                    "inspectionUrl": inspect_url,
                    "siteUrl": site_url,
                },
            )
            if resp.status_code != 200:
                log.error("GSC inspect_url failed: %s %s", resp.status_code, resp.text[:300])
                return {"error": f"API error: {resp.status_code}"}
            return resp.json()
