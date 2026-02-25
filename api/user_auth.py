"""User authentication via Supabase Auth.

Flow:
  - Users sign up / log in via Supabase Auth (frontend handles UI)
  - Frontend sends Supabase access_token as Authorization: Bearer header
  - Backend validates JWT, resolves profile from `profiles` table
  - Profile resolves to org list via user_orgs

Admin operations use the Supabase service_role client.
"""

import datetime
import os
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session, get_db
from models import AccessRequest, Organization, Profile, UserOrg

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Token Validation (via Supabase client — no JWT secret needed) ─────────────

async def resolve_supabase_user(authorization: str | None = Header(default=None)) -> Profile | None:
    """Validate Supabase access token and return the Profile. Returns None if no token."""
    if not authorization:
        return None

    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        return None

    # Validate token via Supabase Auth API (service_role can read any user)
    try:
        sb = _get_supabase_admin()
        user_response = sb.auth.get_user(token_value)
        if not user_response or not user_response.user:
            return None
        user_id = UUID(str(user_response.user.id))
    except Exception:
        return None

    async with async_session() as session:
        result = await session.execute(
            select(Profile).where(Profile.id == user_id)
        )
        return result.scalar_one_or_none()


async def require_user(authorization: str | None = Header(default=None)) -> Profile:
    """FastAPI dependency — requires a valid Supabase session."""
    profile = await resolve_supabase_user(authorization)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Sign in with Supabase Auth.",
        )
    return profile


async def require_admin(authorization: str | None = Header(default=None)) -> Profile:
    """FastAPI dependency — requires admin profile."""
    profile = await require_user(authorization)
    if not profile.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return profile


# ── Supabase Admin Client ────────────────────────────────────────────────────

def _get_supabase_admin():
    """Get a Supabase client with service_role key for admin operations."""
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ── Public endpoints ──────────────────────────────────────────────────────────

class AccessRequestIn(BaseModel):
    email: str
    name: str = ""
    reason: str = ""


@router.post("/request-access")
async def request_access(body: AccessRequestIn, db: AsyncSession = Depends(get_db)):
    """Public waitlist / access request form."""
    email = body.email.lower()

    dup = await db.execute(
        select(AccessRequest).where(
            AccessRequest.email == email,
            AccessRequest.status == "pending",
        )
    )
    if dup.scalar_one_or_none():
        return {"ok": True, "message": "Request already received — we'll be in touch."}

    req = AccessRequest(email=email, name=body.name, reason=body.reason)
    db.add(req)
    await db.commit()

    # Also write to Supabase waitlist table so admin dashboard sees it
    try:
        import httpx
        sb_url = os.environ.get("SUPABASE_URL", "")
        sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if sb_url and sb_key:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{sb_url}/rest/v1/waitlist",
                    headers={
                        "apikey": sb_key,
                        "Authorization": f"Bearer {sb_key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal",
                    },
                    json={"email": email, "message": body.reason or ""},
                    timeout=5,
                )
    except Exception:
        pass  # Don't fail the request if Supabase write fails

    return {"ok": True, "message": "Request received. We'll review and send you an invite."}


# ── Authenticated endpoints ───────────────────────────────────────────────────

@router.get("/me")
async def me(
    profile: Profile = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current user profile + orgs from Supabase JWT."""
    org_result = await db.execute(
        select(Organization)
        .join(UserOrg, UserOrg.org_id == Organization.id)
        .where(UserOrg.user_id == profile.id)
    )
    orgs = [{"id": o.id, "name": o.name, "domain": o.domain} for o in org_result.scalars().all()]

    return {
        "user": {
            "id": str(profile.id),
            "email": profile.email,
            "name": profile.name,
            "is_admin": bool(profile.is_admin),
        },
        "orgs": orgs,
    }


# ── Admin: user management ────────────────────────────────────────────────────

class CreateUserIn(BaseModel):
    email: str
    name: str = ""
    is_admin: bool = False
    org_ids: list[int] = []


@router.post("/admin/users")
async def admin_create_user(
    body: CreateUserIn,
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: create a user via Supabase Auth and assign orgs."""
    sb = _get_supabase_admin()

    # Create user in Supabase Auth (sends invite email)
    try:
        auth_response = sb.auth.admin.invite_user_by_email(body.email.lower())
        sb_user = auth_response.user
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create user: {e}")

    # Profile is auto-created by DB trigger, but update name/admin
    await db.execute(
        update(Profile)
        .where(Profile.id == sb_user.id)
        .values(name=body.name, is_admin=body.is_admin)
    )

    # Assign orgs
    for org_id in body.org_ids:
        db.add(UserOrg(user_id=sb_user.id, org_id=org_id))

    await db.commit()

    return {
        "user_id": str(sb_user.id),
        "email": body.email.lower(),
        "message": "User invited via Supabase. They'll receive an email.",
    }


@router.get("/admin/users")
async def admin_list_users(
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all profiles."""
    result = await db.execute(select(Profile).order_by(Profile.created_at.desc()))
    profiles = result.scalars().all()
    out = []
    for p in profiles:
        org_result = await db.execute(
            select(Organization)
            .join(UserOrg, UserOrg.org_id == Organization.id)
            .where(UserOrg.user_id == p.id)
        )
        orgs = [{"id": o.id, "name": o.name} for o in org_result.scalars().all()]
        out.append({
            "id": str(p.id),
            "email": p.email,
            "name": p.name,
            "is_admin": bool(p.is_admin),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "orgs": orgs,
        })
    return out


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: delete a user from Supabase Auth and profiles."""
    uid = UUID(user_id)
    result = await db.execute(select(Profile).where(Profile.id == uid))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found.")

    # Delete from Supabase Auth (cascades to profiles via FK)
    try:
        sb = _get_supabase_admin()
        sb.auth.admin.delete_user(user_id)
    except Exception:
        pass

    await db.delete(profile)
    await db.commit()
    return {"ok": True}


# ── Admin: access requests ────────────────────────────────────────────────────

@router.get("/admin/requests")
async def admin_list_requests(
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AccessRequest).order_by(AccessRequest.created_at.desc())
    )
    reqs = result.scalars().all()
    return [
        {
            "id": r.id, "email": r.email, "name": r.name, "reason": r.reason,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reqs
    ]


class ApproveRequestIn(BaseModel):
    org_ids: list[int] = []


@router.post("/admin/requests/{request_id}/approve")
async def admin_approve_request(
    request_id: int,
    body: ApproveRequestIn,
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AccessRequest).where(AccessRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req.status}.")

    # Create user in Supabase Auth
    sb = _get_supabase_admin()
    try:
        auth_response = sb.auth.admin.invite_user_by_email(req.email)
        sb_user = auth_response.user
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to invite user: {e}")

    # Update profile with name
    await db.execute(
        update(Profile)
        .where(Profile.id == sb_user.id)
        .values(name=req.name)
    )

    # Assign orgs
    for org_id in body.org_ids:
        dup = await db.execute(
            select(UserOrg).where(UserOrg.user_id == sb_user.id, UserOrg.org_id == org_id)
        )
        if not dup.scalar_one_or_none():
            db.add(UserOrg(user_id=sb_user.id, org_id=org_id))

    await db.execute(
        update(AccessRequest).where(AccessRequest.id == request_id).values(
            status="approved",
            reviewed_at=datetime.datetime.utcnow(),
        )
    )
    await db.commit()

    return {"ok": True, "user_id": str(sb_user.id), "message": "User invited via Supabase."}


@router.post("/admin/requests/{request_id}/reject")
async def admin_reject_request(
    request_id: int,
    admin: Profile = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AccessRequest).where(AccessRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    await db.execute(
        update(AccessRequest).where(AccessRequest.id == request_id).values(
            status="rejected",
            reviewed_at=datetime.datetime.utcnow(),
        )
    )
    await db.commit()
    return {"ok": True}


# ── User API keys ─────────────────────────────────────────────────────────────

class CreateApiKeyIn(BaseModel):
    label: str = ""
    org_id: int


@router.post("/api-keys")
async def create_api_key(
    body: CreateApiKeyIn,
    profile: Profile = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for the authenticated user, scoped to an org."""
    import secrets
    # Verify user has access to this org
    access = await db.execute(
        select(UserOrg).where(UserOrg.user_id == profile.id, UserOrg.org_id == body.org_id)
    )
    if not access.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You don't have access to this organization.")

    token_value = f"pr_{secrets.token_urlsafe(32)}"
    from models import ApiToken
    api_token = ApiToken(
        org_id=body.org_id,
        token=token_value,
        label=body.label or "default",
    )
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    return {
        "id": api_token.id,
        "token": token_value,  # Only shown once!
        "label": api_token.label,
        "org_id": api_token.org_id,
        "created_at": api_token.created_at.isoformat() if api_token.created_at else None,
        "message": "Save this token — it won't be shown again.",
    }


@router.get("/api-keys")
async def list_api_keys(
    profile: Profile = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """List API keys for orgs the authenticated user has access to."""
    from models import ApiToken
    # Get user's org IDs
    org_result = await db.execute(
        select(UserOrg.org_id).where(UserOrg.user_id == profile.id)
    )
    org_ids = [row[0] for row in org_result.all()]

    if not org_ids:
        return []

    result = await db.execute(
        select(ApiToken)
        .join(Organization, Organization.id == ApiToken.org_id)
        .where(ApiToken.org_id.in_(org_ids), ApiToken.revoked == False)
        .order_by(ApiToken.created_at.desc())
    )
    tokens = result.scalars().all()

    return [
        {
            "id": t.id,
            "label": t.label,
            "org_id": t.org_id,
            "token_prefix": t.token[:7] + "..." if t.token else "",
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    profile: Profile = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    from models import ApiToken
    result = await db.execute(select(ApiToken).where(ApiToken.id == key_id))
    api_token = result.scalar_one_or_none()
    if not api_token:
        raise HTTPException(status_code=404, detail="API key not found.")

    # Verify user has access to the key's org
    access = await db.execute(
        select(UserOrg).where(UserOrg.user_id == profile.id, UserOrg.org_id == api_token.org_id)
    )
    if not access.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not authorized.")

    await db.execute(
        update(ApiToken).where(ApiToken.id == key_id).values(revoked=True)
    )
    await db.commit()
    return {"ok": True}
