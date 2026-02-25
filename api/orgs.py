"""Organization endpoints — create, list, switch companies."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import get_authenticated_data_layer, resolve_token
from database import async_session
from models import Organization, Profile, UserOrg
from services.data_layer import DataLayer

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


class CreateOrgRequest(BaseModel):
    name: str
    domain: str = ""


@router.get("")
async def list_orgs(
    dl: DataLayer = Depends(get_authenticated_data_layer),
    auth_info: dict | None = Depends(resolve_token),
):
    """List orgs the user has access to, plus demo orgs. Admins/API tokens see all orgs."""
    user_id = auth_info.get("user_id") if auth_info else None
    full_access = auth_info.get("full_access", False) if auth_info else False

    async with async_session() as session:
        # Check if user is admin
        is_admin = False
        if user_id:
            profile = await session.execute(
                select(Profile).where(Profile.id == user_id)
            )
            p = profile.scalar_one_or_none()
            is_admin = p.is_admin if p else False

        # Admins and API tokens see every org
        if is_admin or full_access:
            result = await session.execute(
                select(Organization).order_by(Organization.created_at.desc())
            )
            return [
                {"id": o.id, "name": o.name, "domain": o.domain,
                 "created_at": o.created_at.isoformat() if o.created_at else None}
                for o in result.scalars().all()
            ]

        # Non-admin: user's orgs + demo orgs
        user_org_ids = set()
        if user_id:
            result = await session.execute(
                select(UserOrg.org_id).where(UserOrg.user_id == user_id)
            )
            user_org_ids = {row[0] for row in result.fetchall()}

        result = await session.execute(
            select(Organization.id).where(Organization.is_demo == True)
        )
        demo_org_ids = {row[0] for row in result.fetchall()}

        all_ids = user_org_ids | demo_org_ids
        if not all_ids:
            return []

        result = await session.execute(
            select(Organization)
            .where(Organization.id.in_(all_ids))
            .order_by(Organization.created_at.desc())
        )
        return [
            {"id": o.id, "name": o.name, "domain": o.domain,
             "created_at": o.created_at.isoformat() if o.created_at else None}
            for o in result.scalars().all()
        ]


@router.post("")
async def create_org(req: CreateOrgRequest,
                     dl: DataLayer = Depends(get_authenticated_data_layer),
                     auth_info: dict | None = Depends(resolve_token)):
    """Create a new organization and link the creating user to it."""
    org = await dl.create_org(name=req.name, domain=req.domain)

    # Auto-link the creating user to this org
    user_id = auth_info.get("user_id") if auth_info else None
    if user_id:
        dl.db.add(UserOrg(user_id=user_id, org_id=org["id"]))

    await dl.commit()
    return org


@router.get("/{org_id}")
async def get_org(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get a single organization."""
    org = await dl.get_org(org_id)
    if not org:
        return {"error": "Organization not found"}
    return org


@router.delete("/{org_id}")
async def delete_org(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Delete an organization."""
    deleted = await dl.delete_org(org_id)
    await dl.commit()
    return {"deleted": deleted}


async def _run_onboard_sequence(org_id: int, name: str, domain: str):
    """Run the full onboard sequence using service layer directly.

    SEO audit → synthetic signal → First Blog story → generate blog+linkedin.
    Called in background — no request context.
    """
    from database import async_session as make_session
    from services.data_layer import DataLayer
    from services.seo_audit import audit_domain
    from services.engine import generate_from_story

    log.info("Onboard sequence starting for org %s (%s / %s)", org_id, name, domain)
    steps = {}

    try:
        async with make_session() as session:
            dl = DataLayer(session, org_id=org_id)
            api_key = await dl.resolve_api_key()

            # 1. SEO audit
            audit_summary = ""
            try:
                audit_result = await audit_domain(domain, max_pages=15, api_key=api_key)
                if "error" not in audit_result:
                    await dl.save_audit({
                        "audit_type": "seo",
                        "target": domain,
                        "result": audit_result,
                    })
                    audit_summary = audit_result.get("recommendations", {}).get("score_summary", "")
                    steps["audit"] = "ok"
                else:
                    steps["audit"] = f"err: {audit_result['error'][:80]}"
            except Exception as e:
                steps["audit"] = f"exception: {e}"
                log.warning("Onboard audit failed for %s: %s", domain, e)

            # 2. Synthetic "about" signal
            about_content = (
                f"{name} is a company at {domain}. "
                f"{audit_summary} "
                f"This is the founding story signal for content generation."
            ).strip()
            signal = await dl.save_signal({
                "type": "web_search",
                "source": domain,
                "title": f"About {name}",
                "content": about_content,
                "url": f"https://{domain}",
            })
            signal_id = signal.get("id") if signal else None
            steps["signal"] = f"id:{signal_id}" if signal_id else "err"

            # 3. First Blog story
            story = await dl.create_story({
                "title": f"{name} — First Blog",
                "angle": f"Introducing {name}: what we do, who we serve, and why we built it.",
                "editorial_notes": "Keep it human. No jargon. Tell the founding story.",
            })
            story_id = story.get("id") if story else None

            if story_id:
                steps["story"] = f"id:{story_id}"
                if signal_id:
                    await dl.add_signal_to_story(story_id, signal_id)

                # 4. Generate blog + linkedin
                try:
                    story_obj = await dl.get_story(story_id)
                    results = await generate_from_story(
                        story_obj, dl, channels=["blog", "linkedin"], api_key=api_key
                    )
                    steps["generate"] = f"{len(results)} pieces"
                except Exception as e:
                    steps["generate"] = f"err: {e}"
                    log.warning("Onboard generate failed for story %s: %s", story_id, e)
            else:
                steps["story"] = "err"

            await dl.commit()

        log.info("Onboard sequence complete for org %s: %s", org_id, steps)
    except Exception as e:
        log.error("Onboard sequence failed for org %s: %s", org_id, e)


@router.post("/{org_id}/onboard")
async def onboard_org(
    org_id: int,
    background_tasks: BackgroundTasks,
    dl: DataLayer = Depends(get_authenticated_data_layer),
    auth_info: dict | None = Depends(resolve_token),
):
    """Trigger the full onboard sequence for an existing org.

    Runs SEO audit, creates synthetic signal, generates First Blog story + content.
    Fires in background — returns immediately.
    """
    user_id = auth_info.get("user_id") if auth_info else None

    # Check authorization: admin or member of this org
    is_admin = False
    if user_id:
        async with async_session() as session:
            p = (await session.execute(
                select(Profile).where(Profile.id == user_id)
            )).scalar_one_or_none()
            is_admin = p.is_admin if p else False

    if not is_admin and user_id:
        async with async_session() as session:
            uo = (await session.execute(
                select(UserOrg).where(UserOrg.user_id == user_id, UserOrg.org_id == org_id)
            )).scalar_one_or_none()
            if not uo:
                raise HTTPException(status_code=403, detail="Not authorized for this org")

    org = await dl.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")

    name = org.get("name", "")
    domain = org.get("domain", "")

    if not domain:
        raise HTTPException(status_code=400, detail="Org has no domain — set one first")

    background_tasks.add_task(_run_onboard_sequence, org_id, name, domain)

    return {"status": "onboard_started", "org_id": org_id, "name": name, "domain": domain}
