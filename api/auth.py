"""API authentication — supports both API tokens (pr_*) and Supabase JWTs.

API tokens: scoped to an org, used by MCP and external integrations.
Supabase JWTs: issued by Supabase Auth, used by the frontend.

Bypass: if PRESSROOM_AUTH_DISABLED=1, auth is skipped and X-Org-Id header
is used directly (for local development).
"""

import base64
import datetime
import logging
import os
import secrets

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from database import async_session
from models import ApiToken, Profile, UserOrg

log = logging.getLogger("pressroom")

# Skip auth in dev mode (set PRESSROOM_AUTH_DISABLED=1)
AUTH_DISABLED = os.getenv("PRESSROOM_AUTH_DISABLED", "").strip() in ("1", "true", "yes")

# Supabase JWT secret for verifying frontend tokens
_raw_secret = app_settings.supabase_jwt_secret
SUPABASE_JWT_SECRET = base64.b64decode(_raw_secret) if _raw_secret else b""


async def resolve_token(
    authorization: str | None = Header(default=None),
    x_org_id: int | None = Header(default=None),
) -> dict | None:
    """Extract and validate a bearer token from the Authorization header.

    Supports two token types:
      - pr_* API tokens → looked up in api_tokens table, org from token
      - Supabase JWTs   → verified with JWT secret, org from profile or X-Org-Id

    Returns dict with {"type": "api_token"|"supabase", "org_id": int|None}
    or None if auth is disabled.
    """
    if AUTH_DISABLED:
        return None

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Use: Authorization: Bearer <token>",
        )

    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header. Use: Authorization: Bearer <token>",
        )

    # ── API token (pr_*) ──
    if token_value.startswith("pr_"):
        async with async_session() as session:
            result = await session.execute(
                select(ApiToken).where(ApiToken.token == token_value)
            )
            api_token = result.scalar_one_or_none()

            if api_token is None or api_token.revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or revoked API token.",
                )

            # Touch last_used_at
            await session.execute(
                update(ApiToken)
                .where(ApiToken.id == api_token.id)
                .values(last_used_at=datetime.datetime.utcnow())
            )
            await session.commit()

            return {"type": "api_token", "org_id": api_token.org_id, "full_access": True}

    # ── Supabase JWT ──
    # Try local JWT decode first (HS256), fall back to Supabase API (handles ES256)
    user_id = None
    try:
        if SUPABASE_JWT_SECRET:
            payload = jwt.decode(
                token_value,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            user_id = payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired. Please log in again.",
        )
    except jwt.InvalidTokenError:
        pass  # Fall through to Supabase API validation

    # Fallback: validate via Supabase Auth API (works with ES256 and any algorithm)
    if not user_id:
        try:
            from api.user_auth import _get_supabase_admin
            from uuid import UUID
            sb = _get_supabase_admin()
            user_response = sb.auth.get_user(token_value)
            if user_response and user_response.user:
                user_id = str(user_response.user.id)
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token.",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token.",
            )
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub claim.",
        )

    # Look up user's org from user_orgs table (use X-Org-Id if they have access)
    org_id = None
    read_only = False
    async with async_session() as session:
        result = await session.execute(
            select(UserOrg.org_id).where(UserOrg.user_id == user_id)
        )
        user_org_ids = [row[0] for row in result.fetchall()]

        # Check if user is admin
        is_admin = False
        profile = await session.execute(
            select(Profile.is_admin).where(Profile.id == user_id)
        )
        row = profile.scalar_one_or_none()
        if row:
            is_admin = row

        if x_org_id and (x_org_id in user_org_ids or is_admin):
            org_id = x_org_id  # user is a member of this org (or admin)
        elif x_org_id:
            # Allow demo orgs — read-only for non-members
            from models import Organization
            demo = await session.execute(
                select(Organization.id).where(
                    Organization.id == x_org_id, Organization.is_demo == True
                )
            )
            if demo.scalar_one_or_none():
                org_id = x_org_id
                read_only = True
            else:
                # User explicitly requested an org they don't belong to — reject
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have access to this organization.",
                )
        elif user_org_ids:
            org_id = user_org_ids[0]  # default to first org

    return {"type": "supabase", "org_id": org_id, "user_id": user_id, "read_only": read_only}


async def get_authenticated_data_layer(
    auth_info: dict | None = Depends(resolve_token),
    x_org_id: int | None = Header(default=None),
):
    """FastAPI dependency — yields a DataLayer with org resolved from auth.

    Accepts both pr_* API tokens and Supabase JWTs.
    In dev mode (PRESSROOM_AUTH_DISABLED=1): falls back to X-Org-Id header.
    Demo orgs are read-only for non-admin non-members.
    """
    from services.data_layer import DataLayer

    if auth_info is not None:
        # API tokens are scoped to their org — ignore X-Org-Id override
        org_id = auth_info.get("org_id") or x_org_id
        read_only = auth_info.get("read_only", False)
    else:
        org_id = x_org_id
        read_only = False

    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id, read_only=read_only)
        yield dl


async def resolve_sse_auth(authorization: str | None, x_org_id: int | None) -> tuple[int | None, bool]:
    """Resolve org_id + read_only for SSE endpoints (query params, not headers).

    EventSource can't send custom headers, so SSE endpoints pass the token
    as a query parameter. Returns (org_id, read_only).
    Raises HTTPException on auth failure.
    """
    if AUTH_DISABLED:
        return x_org_id, False

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization parameter.",
        )

    # Reuse resolve_token logic by calling it directly (not as a dependency)
    auth_info = await resolve_token(
        authorization=f"Bearer {authorization}",
        x_org_id=x_org_id,
    )
    if auth_info is None:
        return x_org_id, False

    org_id = auth_info.get("org_id") or x_org_id
    read_only = auth_info.get("read_only", False)
    return org_id, read_only


async def create_token(session: AsyncSession, org_id: int, label: str = "") -> ApiToken:
    """Create a new API token for an org."""
    token_value = f"pr_{secrets.token_urlsafe(32)}"
    api_token = ApiToken(
        org_id=org_id,
        token=token_value,
        label=label or "default",
    )
    session.add(api_token)
    await session.commit()
    await session.refresh(api_token)
    return api_token
