"""User authentication — login, invite, access requests, admin approval.

Flow:
  - Admin pre-creates users (or approves requests) → invite token generated
  - User visits /invite/{token} → sets password → account activated
  - User logs in → UserSession token issued → stored in browser localStorage
  - All API calls carry session token in Authorization: Bearer header
  - Session token resolves to user → user resolves to org list
"""

import datetime
import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from models import AccessRequest, InviteToken, Organization, User, UserOrg, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL_DAYS = 30
INVITE_TTL_HOURS = 72


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
    except Exception:
        return False


def _make_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


async def resolve_session(authorization: str | None = None) -> User | None:
    """Resolve a session token to a User. Returns None if invalid/expired."""
    if not authorization:
        return None
    scheme, _, token_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token_value:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(UserSession).where(UserSession.token == token_value)
        )
        sess = result.scalar_one_or_none()
        if not sess or sess.expires_at < datetime.datetime.utcnow():
            return None
        result2 = await session.execute(select(User).where(User.id == sess.user_id))
        return result2.scalar_one_or_none()


async def require_user(authorization: str | None = None) -> User:
    from fastapi import Header
    user = await resolve_session(authorization)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


async def require_admin(authorization: str | None = None) -> User:
    from fastapi import Header
    user = await resolve_session(authorization)
    if not user or not user.is_active or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


# ── Request access ─────────────────────────────────────────────────────────────

class AccessRequestIn(BaseModel):
    email: str
    name: str = ""
    reason: str = ""


@router.post("/request-access")
async def request_access(body: AccessRequestIn, db: AsyncSession = Depends(get_db)):
    # Check if already a user
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    # Check for duplicate pending request
    dup = await db.execute(
        select(AccessRequest).where(
            AccessRequest.email == body.email.lower(),
            AccessRequest.status == "pending",
        )
    )
    if dup.scalar_one_or_none():
        return {"ok": True, "message": "Request already received — we'll be in touch."}

    req = AccessRequest(
        email=body.email.lower(),
        name=body.name,
        reason=body.reason,
    )
    db.add(req)
    await db.commit()
    return {"ok": True, "message": "Request received. We'll review and send you an invite."}


# ── Login ──────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Issue session token
    token_value = _make_token("ps_")
    expires = datetime.datetime.utcnow() + datetime.timedelta(days=SESSION_TTL_DAYS)
    sess = UserSession(user_id=user.id, token=token_value, expires_at=expires)
    db.add(sess)

    await db.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.datetime.utcnow())
    )
    await db.commit()

    # Return orgs this user has access to
    org_result = await db.execute(
        select(Organization)
        .join(UserOrg, UserOrg.org_id == Organization.id)
        .where(UserOrg.user_id == user.id)
    )
    orgs = [{"id": o.id, "name": o.name, "domain": o.domain} for o in org_result.scalars().all()]

    return {
        "token": token_value,
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin)},
        "orgs": orgs,
    }


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    if authorization:
        _, _, token_value = authorization.partition(" ")
        await db.execute(
            select(UserSession).where(UserSession.token == token_value)
        )
        # Just expire it
        await db.execute(
            update(UserSession)
            .where(UserSession.token == token_value)
            .values(expires_at=datetime.datetime.utcnow())
        )
        await db.commit()
    return {"ok": True}


@router.get("/me")
async def me(authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)):
    """Return current user + orgs from session token."""
    user = await resolve_session(authorization)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")

    org_result = await db.execute(
        select(Organization)
        .join(UserOrg, UserOrg.org_id == Organization.id)
        .where(UserOrg.user_id == user.id)
    )
    orgs = [{"id": o.id, "name": o.name, "domain": o.domain} for o in org_result.scalars().all()]

    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "is_admin": bool(user.is_admin)},
        "orgs": orgs,
    }


# ── Invite flow ────────────────────────────────────────────────────────────────

class SetPasswordIn(BaseModel):
    token: str
    password: str


@router.post("/set-password")
async def set_password(body: SetPasswordIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(InviteToken).where(InviteToken.token == body.token))
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=400, detail="Invalid invite link.")
    if invite.used_at:
        raise HTTPException(status_code=400, detail="This invite link has already been used.")
    if invite.expires_at < datetime.datetime.utcnow():
        raise HTTPException(status_code=400, detail="This invite link has expired.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    # Activate user
    result2 = await db.execute(select(User).where(User.email == invite.email))
    user = result2.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="User not found.")

    await db.execute(
        update(User).where(User.id == user.id).values(
            password_hash=_hash_password(body.password),
            is_active=1,
        )
    )
    await db.execute(
        update(InviteToken).where(InviteToken.id == invite.id).values(
            used_at=datetime.datetime.utcnow()
        )
    )
    await db.commit()
    return {"ok": True, "message": "Password set. You can now log in."}


@router.get("/invite/{token}")
async def check_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Validate an invite token — used by frontend before showing set-password form."""
    result = await db.execute(select(InviteToken).where(InviteToken.token == token))
    invite = result.scalar_one_or_none()

    if not invite or invite.used_at:
        return {"valid": False, "reason": "used"}
    if invite.expires_at < datetime.datetime.utcnow():
        return {"valid": False, "reason": "expired"}
    return {"valid": True, "email": invite.email}


# ── Admin: create user + invite ────────────────────────────────────────────────

class CreateUserIn(BaseModel):
    email: str
    name: str = ""
    is_admin: bool = False
    org_ids: list[int] = []


@router.post("/admin/users")
async def admin_create_user(body: CreateUserIn, db: AsyncSession = Depends(get_db)):
    """Admin: pre-create a user account and generate an invite link."""
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already exists.")

    user = User(
        email=body.email.lower(),
        name=body.name,
        is_admin=1 if body.is_admin else 0,
        is_active=0,
    )
    db.add(user)
    await db.flush()

    # Assign orgs
    for org_id in body.org_ids:
        db.add(UserOrg(user_id=user.id, org_id=org_id))

    # Generate invite token
    token_value = _make_token("inv_")
    expires = datetime.datetime.utcnow() + datetime.timedelta(hours=INVITE_TTL_HOURS)
    invite = InviteToken(token=token_value, email=body.email.lower(), user_id=user.id, expires_at=expires)
    db.add(invite)
    await db.commit()

    return {
        "user_id": user.id,
        "email": user.email,
        "invite_token": token_value,
        "invite_link": f"/invite/{token_value}",
        "expires_at": expires.isoformat(),
    }


@router.post("/admin/users/{user_id}/reinvite")
async def admin_reinvite(user_id: int, db: AsyncSession = Depends(get_db)):
    """Re-generate an invite link for an existing user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    token_value = _make_token("inv_")
    expires = datetime.datetime.utcnow() + datetime.timedelta(hours=INVITE_TTL_HOURS)
    invite = InviteToken(token=token_value, email=user.email, user_id=user.id, expires_at=expires)
    db.add(invite)
    await db.commit()

    return {
        "invite_token": token_value,
        "invite_link": f"/invite/{token_value}",
        "expires_at": expires.isoformat(),
    }


@router.get("/admin/users")
async def admin_list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    out = []
    for u in users:
        org_result = await db.execute(
            select(Organization)
            .join(UserOrg, UserOrg.org_id == Organization.id)
            .where(UserOrg.user_id == u.id)
        )
        orgs = [{"id": o.id, "name": o.name} for o in org_result.scalars().all()]
        out.append({
            "id": u.id, "email": u.email, "name": u.name,
            "is_admin": bool(u.is_admin), "is_active": bool(u.is_active),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "orgs": orgs,
        })
    return out


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    await db.delete(user)
    await db.commit()
    return {"ok": True}


# ── Admin: access requests ─────────────────────────────────────────────────────

@router.get("/admin/requests")
async def admin_list_requests(db: AsyncSession = Depends(get_db)):
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
    request_id: int, body: ApproveRequestIn, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AccessRequest).where(AccessRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req.status}.")

    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == req.email))
    user = existing.scalar_one_or_none()
    if not user:
        user = User(email=req.email, name=req.name, is_admin=0, is_active=0)
        db.add(user)
        await db.flush()

    for org_id in body.org_ids:
        dup = await db.execute(
            select(UserOrg).where(UserOrg.user_id == user.id, UserOrg.org_id == org_id)
        )
        if not dup.scalar_one_or_none():
            db.add(UserOrg(user_id=user.id, org_id=org_id))

    # Generate invite
    token_value = _make_token("inv_")
    expires = datetime.datetime.utcnow() + datetime.timedelta(hours=INVITE_TTL_HOURS)
    invite = InviteToken(token=token_value, email=req.email, user_id=user.id, expires_at=expires)
    db.add(invite)

    await db.execute(
        update(AccessRequest).where(AccessRequest.id == request_id).values(
            status="approved",
            reviewed_at=datetime.datetime.utcnow(),
        )
    )
    await db.commit()

    return {
        "ok": True,
        "user_id": user.id,
        "invite_link": f"/invite/{token_value}",
        "invite_token": token_value,
    }


@router.post("/admin/requests/{request_id}/reject")
async def admin_reject_request(request_id: int, db: AsyncSession = Depends(get_db)):
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
