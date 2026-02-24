"""API token authentication.

Bearer token auth for the Pressroom API. Tokens are scoped to an org —
a valid token authenticates the request AND sets the org context.

Bypass: if PRESSROOM_AUTH_DISABLED=1 env var is set, auth is skipped and
X-Org-Id header is used directly (for local development).
"""

import datetime
import os
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models import ApiToken


# Skip auth in dev mode (set PRESSROOM_AUTH_DISABLED=1)
AUTH_DISABLED = os.getenv("PRESSROOM_AUTH_DISABLED", "").strip() in ("1", "true", "yes")


async def resolve_token(authorization: str | None = Header(default=None)) -> ApiToken | None:
    """Extract and validate a bearer token from the Authorization header.

    Returns the ApiToken row if valid, None if auth is disabled.
    Raises 401 if token is missing/invalid/revoked.
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

        return api_token


def get_org_id_from_token(
    api_token: ApiToken | None = Depends(resolve_token),
    x_org_id: int | None = Header(default=None),
) -> int | None:
    """Resolve org_id from token (production) or X-Org-Id header (dev mode).

    In production: org_id comes from the validated token.
    In dev mode (AUTH_DISABLED): falls back to X-Org-Id header.
    """
    if api_token is not None:
        return api_token.org_id
    return x_org_id


async def get_authenticated_data_layer(
    org_id: int | None = Depends(get_org_id_from_token),
):
    """FastAPI dependency — yields a DataLayer with org resolved from auth token.

    In production: org_id comes from the validated bearer token.
    In dev mode (PRESSROOM_AUTH_DISABLED=1): falls back to X-Org-Id header.

    Use this instead of database.get_data_layer for authenticated routes.
    """
    from services.data_layer import DataLayer
    async with async_session() as session:
        dl = DataLayer(session, org_id=org_id)
        yield dl


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
