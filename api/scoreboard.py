"""Scoreboard API — org rankings by SEO score and content activity."""

import json
from datetime import datetime, timedelta
from fastapi import APIRouter
from sqlalchemy import select, func, desc

from database import async_session
from models import Organization, AuditResult, Signal, Content, Setting, TeamMember

router = APIRouter(prefix="/api/scoreboard", tags=["scoreboard"])


@router.get("")
async def get_scoreboard():
    """Return all orgs ranked by latest SEO score with GEO detail."""
    async with async_session() as session:
        result = await session.execute(select(Organization).order_by(Organization.name))
        orgs = result.scalars().all()

        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        scoreboard = []

        for org in orgs:
            # Latest audit result
            audit_res = await session.execute(
                select(AuditResult)
                .where(AuditResult.org_id == org.id)
                .order_by(desc(AuditResult.created_at))
                .limit(1)
            )
            latest_audit = audit_res.scalars().first()

            seo_score = latest_audit.score if latest_audit else None
            latest_audit_id = latest_audit.id if latest_audit else None
            audit_date = latest_audit.created_at.isoformat() if latest_audit and latest_audit.created_at else None
            ai_citability = "Unknown"
            p0_count = 0
            p1_count = 0
            top_opportunity = None
            blocked_bots = []

            if latest_audit and latest_audit.result_json:
                try:
                    rj = json.loads(latest_audit.result_json) if isinstance(latest_audit.result_json, str) else latest_audit.result_json
                    ai_citability = rj.get("ai_citability", "Unknown")
                    recs = rj.get("recommendations", [])
                    p0_count = sum(1 for r in recs if r.get("priority") == "P0")
                    p1_count = sum(1 for r in recs if r.get("priority") == "P1")
                    top = (
                        next((r for r in recs if r.get("priority") == "P0"), None)
                        or next((r for r in recs if r.get("priority") == "P1"), None)
                        or (recs[0] if recs else None)
                    )
                    if top:
                        top_opportunity = top.get("action", "")[:80]
                    blocked_bots = rj.get("robots", {}).get("blocked_bots", [])
                except Exception:
                    pass

            # Signal count last 7 days
            sig_count_res = await session.execute(
                select(func.count(Signal.id))
                .where(Signal.org_id == org.id)
                .where(Signal.created_at >= seven_days_ago)
            )
            signals_count = sig_count_res.scalar() or 0

            # Published content all time
            pub_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org.id)
                .where(Content.status == "published")
            )
            content_published = pub_res.scalar() or 0

            # Published this week
            pub_week_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org.id)
                .where(Content.status == "published")
                .where(Content.published_at >= seven_days_ago)
            )
            content_this_week = pub_week_res.scalar() or 0

            # GSC connection status — check settings for token or service account
            gsc_connected = False
            gsc_property = ""
            gsc_res = await session.execute(
                select(Setting)
                .where(Setting.org_id == org.id)
                .where(Setting.key.in_(["gsc_access_token", "gsc_service_account_json", "gsc_property"]))
            )
            gsc_settings = {s.key: s.value for s in gsc_res.scalars().all()}
            if gsc_settings.get("gsc_access_token") or gsc_settings.get("gsc_service_account_json"):
                gsc_connected = True
                gsc_property = gsc_settings.get("gsc_property", "")

            # Last active
            last_sig = await session.execute(
                select(Signal.created_at)
                .where(Signal.org_id == org.id)
                .order_by(desc(Signal.created_at))
                .limit(1)
            )
            last_content = await session.execute(
                select(Content.created_at)
                .where(Content.org_id == org.id)
                .order_by(desc(Content.created_at))
                .limit(1)
            )
            ls = last_sig.scalar()
            lc = last_content.scalar()
            last_active = max(ls, lc) if ls and lc else (ls or lc)

            scoreboard.append({
                "org_id": org.id,
                "org_name": org.name,
                "domain": org.domain or "",
                "seo_score": seo_score,
                "ai_citability": ai_citability,
                "p0_count": p0_count,
                "p1_count": p1_count,
                "top_opportunity": top_opportunity,
                "blocked_bots": blocked_bots,
                "latest_audit_id": latest_audit_id,
                "audit_date": audit_date,
                "signals_count": signals_count,
                "content_published": content_published,
                "content_this_week": content_this_week,
                "last_active": last_active.isoformat() if last_active else None,
                "gsc_connected": gsc_connected,
                "gsc_property": gsc_property,
            })

        # Sort by SEO score descending (None last)
        scoreboard.sort(key=lambda x: (x["seo_score"] is not None, x["seo_score"] or 0), reverse=True)
        return scoreboard


@router.get("/{org_id}/team-activity")
async def get_team_activity(org_id: int):
    """Per-member content activity for a given org — for scoreboard drill-down."""
    async with async_session() as session:
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        # Get team members
        members_res = await session.execute(
            select(TeamMember).where(TeamMember.org_id == org_id)
        )
        members = members_res.scalars().all()

        # Org-level content counts (author = 'company' or no author match)
        activity = []
        member_names = {m.name for m in members}

        for member in members:
            # Published all time — match by name in author field
            pub_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org_id)
                .where(Content.status == "published")
                .where(Content.author == member.name)
            )
            published_total = pub_res.scalar() or 0

            # Published this week
            pub_week_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org_id)
                .where(Content.status == "published")
                .where(Content.author == member.name)
                .where(Content.published_at >= seven_days_ago)
            )
            published_week = pub_week_res.scalar() or 0

            # Queued (generated, not yet approved)
            queued_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org_id)
                .where(Content.status == "queued")
                .where(Content.author == member.name)
            )
            queued = queued_res.scalar() or 0

            # Approved (ready to publish)
            approved_res = await session.execute(
                select(func.count(Content.id))
                .where(Content.org_id == org_id)
                .where(Content.status == "approved")
                .where(Content.author == member.name)
            )
            approved = approved_res.scalar() or 0

            # Most recent content
            last_res = await session.execute(
                select(Content.created_at, Content.channel, Content.status)
                .where(Content.org_id == org_id)
                .where(Content.author == member.name)
                .order_by(desc(Content.created_at))
                .limit(1)
            )
            last_row = last_res.first()

            activity.append({
                "member_id": member.id,
                "name": member.name,
                "title": member.title or "",
                "photo_url": member.photo_url or "",
                "github_username": member.github_username or "",
                "linkedin_connected": bool(member.linkedin_author_urn),
                "published_total": published_total,
                "published_week": published_week,
                "queued": queued,
                "approved": approved,
                "last_channel": last_row.channel if last_row else None,
                "last_active": last_row.created_at.isoformat() if last_row and last_row.created_at else None,
            })

        # Also count company-level (author = 'company' or not matching any member)
        company_pub_res = await session.execute(
            select(func.count(Content.id))
            .where(Content.org_id == org_id)
            .where(Content.status == "published")
            .where(~Content.author.in_(member_names))
        )
        company_published = company_pub_res.scalar() or 0

        # Sort: most published first
        activity.sort(key=lambda x: (x["published_total"], x["published_week"]), reverse=True)

        return {
            "org_id": org_id,
            "members": activity,
            "company_published": company_published,
        }
