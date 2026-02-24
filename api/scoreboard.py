"""Scoreboard API — org rankings by SEO score and content activity."""

from datetime import datetime, timedelta
from fastapi import APIRouter
from sqlalchemy import select, func, desc

from database import async_session
from models import Organization, AuditResult, Signal, Content

router = APIRouter(prefix="/api/scoreboard", tags=["scoreboard"])


@router.get("")
async def get_scoreboard():
    """Return all orgs ranked by latest SEO score."""
    async with async_session() as session:
        # Get all orgs
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
            ai_citability = "Unknown"
            if latest_audit and latest_audit.result_json:
                import json
                try:
                    rj = json.loads(latest_audit.result_json) if isinstance(latest_audit.result_json, str) else latest_audit.result_json
                    ai_citability = rj.get("ai_citability", "Unknown")
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
                "signals_count": signals_count,
                "content_published": content_published,
                "content_this_week": content_this_week,
                "last_active": last_active.isoformat() if last_active else None,
            })

        # Sort by SEO score descending (None last)
        scoreboard.sort(key=lambda x: (x["seo_score"] is not None, x["seo_score"] or 0), reverse=True)
        return scoreboard
