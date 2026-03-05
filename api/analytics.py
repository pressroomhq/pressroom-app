"""Analytics dashboard endpoint — single payload for the Pressroom dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy import text

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/dashboard")
async def dashboard(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Single dashboard payload: signal counts, content counts, pipeline timing,
    approval rate, top signals, and top spiked signals."""

    org_filter = "AND org_id = :org_id" if dl.org_id else ""
    params = {"org_id": dl.org_id} if dl.org_id else {}

    # -- Signals: total, by type, by day (last 7) --
    sig_total_q = f"SELECT COUNT(*) FROM signals WHERE 1=1 {org_filter}"
    sig_by_type_q = f"""
        SELECT type, COUNT(*) as cnt
        FROM signals WHERE 1=1 {org_filter}
        GROUP BY type ORDER BY cnt DESC
    """
    sig_by_day_q = f"""
        SELECT created_at::date as day, COUNT(*) as cnt
        FROM signals
        WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' {org_filter}
        GROUP BY created_at::date ORDER BY day
    """

    # -- Content: total, by status, by channel --
    content_total_q = f"SELECT COUNT(*) FROM content WHERE 1=1 {org_filter}"
    content_by_status_q = f"""
        SELECT status, COUNT(*) as cnt
        FROM content WHERE 1=1 {org_filter}
        GROUP BY status ORDER BY cnt DESC
    """
    content_by_channel_q = f"""
        SELECT channel, COUNT(*) as cnt
        FROM content WHERE 1=1 {org_filter}
        GROUP BY channel ORDER BY cnt DESC
    """

    # -- Pipeline timing --
    last_signal_q = f"""
        SELECT MAX(created_at) FROM signals WHERE 1=1 {org_filter}
    """
    last_content_q = f"""
        SELECT MAX(created_at) FROM content WHERE 1=1 {org_filter}
    """

    # -- Approval rate --
    approval_q = f"""
        SELECT
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status = 'spiked' THEN 1 ELSE 0 END) as spiked
        FROM content WHERE 1=1 {org_filter}
    """

    # -- Top signals by times_used --
    top_signals_q = f"""
        SELECT id, type, source, title, COALESCE(times_used, 0) as times_used,
               COALESCE(times_spiked, 0) as times_spiked
        FROM signals
        WHERE COALESCE(times_used, 0) > 0 {org_filter}
        ORDER BY times_used DESC LIMIT 5
    """

    # -- Top spiked signals --
    top_spiked_q = f"""
        SELECT id, type, source, title, COALESCE(times_spiked, 0) as times_spiked,
               COALESCE(times_used, 0) as times_used
        FROM signals
        WHERE COALESCE(times_spiked, 0) > 0 {org_filter}
        ORDER BY times_spiked DESC LIMIT 3
    """

    # -- Last audit score + open action items --
    last_audit_q = f"""
        SELECT score, created_at FROM audit_results
        WHERE audit_type = 'seo' {org_filter}
        ORDER BY created_at DESC LIMIT 1
    """
    open_actions_q = f"""
        SELECT ai.priority, ai.category, ai.title, ai.score_impact
        FROM audit_action_items ai
        WHERE ai.status = 'open'
          AND ai.priority IN ('critical', 'high')
          {org_filter}
        ORDER BY
          CASE ai.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
          ai.score_impact DESC NULLS LAST
        LIMIT 8
    """
    open_actions_count_q = f"""
        SELECT COUNT(*) FROM audit_action_items
        WHERE status = 'open' {org_filter}
    """

    # Execute all queries
    db = dl.db

    sig_total = (await db.execute(text(sig_total_q), params)).scalar() or 0
    sig_by_type_rows = (await db.execute(text(sig_by_type_q), params)).all()
    sig_by_day_rows = (await db.execute(text(sig_by_day_q), params)).all()

    content_total = (await db.execute(text(content_total_q), params)).scalar() or 0
    content_by_status_rows = (await db.execute(text(content_by_status_q), params)).all()
    content_by_channel_rows = (await db.execute(text(content_by_channel_q), params)).all()

    last_signal_at = (await db.execute(text(last_signal_q), params)).scalar()
    last_content_at = (await db.execute(text(last_content_q), params)).scalar()

    approval_row = (await db.execute(text(approval_q), params)).one()
    approved_count = approval_row[0] or 0
    spiked_count = approval_row[1] or 0
    reviewed = approved_count + spiked_count
    approval_rate = round((approved_count / reviewed) * 100, 1) if reviewed > 0 else 0.0

    top_signals_rows = (await db.execute(text(top_signals_q), params)).all()
    top_spiked_rows = (await db.execute(text(top_spiked_q), params)).all()

    # Audit data
    last_audit_row = (await db.execute(text(last_audit_q), params)).first()
    last_audit_score = last_audit_row[0] if last_audit_row else None
    last_audit_at = last_audit_row[1] if last_audit_row else None
    open_actions_rows = (await db.execute(text(open_actions_q), params)).all()
    open_actions_total = (await db.execute(text(open_actions_count_q), params)).scalar() or 0

    return {
        "signals": {
            "total": sig_total,
            "by_type": {row[0]: row[1] for row in sig_by_type_rows},
            "by_day": {row[0]: row[1] for row in sig_by_day_rows},
        },
        "content": {
            "total": content_total,
            "by_status": {row[0]: row[1] for row in content_by_status_rows},
            "by_channel": {row[0]: row[1] for row in content_by_channel_rows},
        },
        "pipeline": {
            "last_scout_run": last_signal_at,
            "last_generate_run": last_content_at,
        },
        "approval_rate": approval_rate,
        "top_signals": [
            {"id": r[0], "type": r[1], "source": r[2], "title": r[3],
             "times_used": r[4], "times_spiked": r[5]}
            for r in top_signals_rows
        ],
        "top_spiked": [
            {"id": r[0], "type": r[1], "source": r[2], "title": r[3],
             "times_spiked": r[4], "times_used": r[5]}
            for r in top_spiked_rows
        ],
        "audit": {
            "last_score": last_audit_score,
            "last_run": str(last_audit_at) if last_audit_at else None,
            "open_actions_total": open_actions_total,
            "open_actions": [
                {"priority": r[0], "category": r[1], "title": r[2],
                 "score_impact": r[3]}
                for r in open_actions_rows
            ],
        },
    }
