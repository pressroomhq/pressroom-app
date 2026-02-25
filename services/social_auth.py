"""Social OAuth — direct token management for LinkedIn, Facebook, YouTube.

Pressroom owns the OAuth flow. Each customer authorizes Pressroom's app
to post on their behalf. Tokens stored per-org in Settings.
"""

import json
import logging
import httpx

log = logging.getLogger("pressroom")


# ──────────────────────────────────────
# LinkedIn OAuth
# ──────────────────────────────────────

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

LINKEDIN_SCOPES = "openid profile w_member_social"


def linkedin_auth_url(client_id: str, redirect_uri: str, state: str = "") -> str:
    """Build the LinkedIn OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": LINKEDIN_SCOPES,
    }
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{LINKEDIN_AUTH_URL}?{qs}"


async def linkedin_exchange_code(client_id: str, client_secret: str,
                                  code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access token."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(LINKEDIN_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        })
        if resp.status_code != 200:
            log.error("LinkedIn token exchange failed: %s %s", resp.status_code, resp.text)
            return {"error": f"Token exchange failed: {resp.status_code}"}
        token_data = resp.json()

        # Get user profile (sub = member ID)
        profile_resp = await c.get(LINKEDIN_USERINFO_URL, headers={
            "Authorization": f"Bearer {token_data['access_token']}"
        })
        profile = profile_resp.json() if profile_resp.status_code == 200 else {}

        return {
            "access_token": token_data.get("access_token"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope"),
            "sub": profile.get("sub", ""),
            "name": profile.get("name", ""),
        }


async def linkedin_post(access_token: str, author_urn: str, text: str,
                        article_url: str = "", article_title: str = "") -> dict:
    """Post to LinkedIn using the REST Posts API (v2 ugcPosts is deprecated)."""
    async with httpx.AsyncClient(timeout=15) as c:
        body = {
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
        }
        # If article URL provided, attach as an article share
        if article_url:
            body["content"] = {
                "article": {
                    "source": article_url,
                    "title": article_title or text[:100],
                },
            }

        resp = await c.post(
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "LinkedIn-Version": "202402",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if resp.status_code in (200, 201):
            post_id = resp.headers.get("x-restli-id", resp.headers.get("x-linkedin-id", ""))
            return {"success": True, "id": post_id}
        # Fallback to legacy ugcPosts if REST API fails (e.g., app not migrated)
        log.warning("LinkedIn REST Posts API failed (%s), trying legacy ugcPosts", resp.status_code)
        return await _linkedin_post_legacy(c, access_token, author_urn, text)


async def _linkedin_post_legacy(client: httpx.AsyncClient, access_token: str,
                                 author_urn: str, text: str) -> dict:
    """Fallback: post via legacy ugcPosts API."""
    resp = await client.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        json={
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        },
    )
    if resp.status_code in (200, 201):
        return {"success": True, "id": resp.headers.get("x-restli-id", "")}
    log.error("LinkedIn post failed: %s %s", resp.status_code, resp.text[:500])
    return {"error": f"LinkedIn API error: {resp.status_code}", "detail": resp.text[:300]}


# ──────────────────────────────────────
# Facebook OAuth
# ──────────────────────────────────────

FB_AUTH_URL = "https://www.facebook.com/v19.0/dialog/oauth"
FB_TOKEN_URL = "https://graph.facebook.com/v19.0/oauth/access_token"
FB_GRAPH_URL = "https://graph.facebook.com/v19.0"

FB_SCOPES = "pages_manage_posts,pages_read_engagement"


def facebook_auth_url(app_id: str, redirect_uri: str, state: str = "") -> str:
    """Build the Facebook OAuth authorization URL."""
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": FB_SCOPES,
        "response_type": "code",
    }
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{FB_AUTH_URL}?{qs}"


async def facebook_exchange_code(app_id: str, app_secret: str,
                                  code: str, redirect_uri: str) -> dict:
    """Exchange code for user token, then get long-lived page token."""
    async with httpx.AsyncClient(timeout=15) as c:
        # Step 1: Exchange code for short-lived user token
        resp = await c.get(FB_TOKEN_URL, params={
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        })
        if resp.status_code != 200:
            log.error("Facebook token exchange failed: %s %s", resp.status_code, resp.text)
            return {"error": f"Token exchange failed: {resp.status_code}"}
        user_token = resp.json().get("access_token")

        # Step 2: Exchange for long-lived token
        ll_resp = await c.get(FB_TOKEN_URL, params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": user_token,
        })
        long_token = ll_resp.json().get("access_token", user_token)

        # Step 3: Get pages this user manages
        pages_resp = await c.get(f"{FB_GRAPH_URL}/me/accounts", params={
            "access_token": long_token,
        })
        pages = pages_resp.json().get("data", []) if pages_resp.status_code == 200 else []

        return {
            "user_access_token": long_token,
            "pages": [{"id": p["id"], "name": p["name"], "access_token": p["access_token"]}
                      for p in pages],
        }


async def facebook_post(page_token: str, page_id: str, message: str) -> dict:
    """Post to a Facebook Page."""
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(
            f"{FB_GRAPH_URL}/{page_id}/feed",
            data={"message": message, "access_token": page_token},
        )
        if resp.status_code == 200:
            return {"success": True, "id": resp.json().get("id", "")}
        log.error("Facebook post failed: %s %s", resp.status_code, resp.text[:500])
        return {"error": f"Facebook API error: {resp.status_code}", "detail": resp.text[:300]}


# ──────────────────────────────────────
# Post Analytics / Performance Tracking
# ──────────────────────────────────────

async def linkedin_post_stats(access_token: str, post_urn: str) -> dict:
    """Fetch engagement stats for a LinkedIn post via socialActions.

    Returns likes, comments, shares counts. Works with w_member_social scope.
    """
    if not post_urn:
        return {}
    async with httpx.AsyncClient(timeout=15) as c:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": "202402",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        stats = {"likes": 0, "comments": 0, "shares": 0}
        try:
            # Likes count
            resp = await c.get(
                f"https://api.linkedin.com/rest/socialActions/{post_urn}/likes",
                headers=headers, params={"count": 0, "start": 0},
            )
            if resp.status_code == 200:
                data = resp.json()
                stats["likes"] = data.get("paging", {}).get("total", 0)

            # Comments count
            resp = await c.get(
                f"https://api.linkedin.com/rest/socialActions/{post_urn}/comments",
                headers=headers, params={"count": 0, "start": 0},
            )
            if resp.status_code == 200:
                data = resp.json()
                stats["comments"] = data.get("paging", {}).get("total", 0)

            return stats
        except Exception as e:
            log.warning("LinkedIn stats fetch failed for %s: %s", post_urn, e)
            return stats


async def devto_post_stats(api_key: str, article_id: str) -> dict:
    """Fetch performance stats for a Dev.to article.

    Returns page_views, reactions, comments.
    """
    if not article_id:
        return {}
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            resp = await c.get(
                f"https://dev.to/api/articles/{article_id}",
                headers={"api-key": api_key},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "impressions": data.get("page_views_count", 0) or 0,
                    "likes": data.get("public_reactions_count", 0) or 0,
                    "comments": data.get("comments_count", 0) or 0,
                }
        except Exception as e:
            log.warning("Dev.to stats fetch failed for article %s: %s", article_id, e)
    return {}


async def facebook_post_stats(page_token: str, post_id: str) -> dict:
    """Fetch engagement stats for a Facebook post.

    Returns likes, comments, shares via Graph API.
    """
    if not post_id or not page_token:
        return {}
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            resp = await c.get(
                f"{FB_GRAPH_URL}/{post_id}",
                params={
                    "fields": "likes.summary(true),comments.summary(true),shares",
                    "access_token": page_token,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "likes": data.get("likes", {}).get("summary", {}).get("total_count", 0),
                    "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                    "shares": data.get("shares", {}).get("count", 0),
                }
        except Exception as e:
            log.warning("Facebook stats fetch failed for %s: %s", post_id, e)
    return {}
