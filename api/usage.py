"""Token usage API — per-org cost tracking and breakdown."""

import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from database import get_data_layer
from models import TokenUsage

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("")
async def get_usage(dl=Depends(get_data_layer)):
    """Total and per-operation token usage for the current org."""
    session = dl.session
    org_id = dl.org_id

    base = select(TokenUsage).where(TokenUsage.org_id == org_id)

    # Totals
    total_q = select(
        func.coalesce(func.sum(TokenUsage.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(TokenUsage.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(TokenUsage.cost_usd), 0).label("cost"),
        func.count(TokenUsage.id).label("calls"),
    ).where(TokenUsage.org_id == org_id)

    total = (await session.execute(total_q)).one()

    # Per-operation breakdown
    op_q = (
        select(
            TokenUsage.operation,
            func.count(TokenUsage.id).label("calls"),
            func.sum(TokenUsage.tokens_in).label("tokens_in"),
            func.sum(TokenUsage.tokens_out).label("tokens_out"),
            func.sum(TokenUsage.cost_usd).label("cost"),
        )
        .where(TokenUsage.org_id == org_id)
        .group_by(TokenUsage.operation)
        .order_by(func.sum(TokenUsage.cost_usd).desc())
    )
    ops = (await session.execute(op_q)).all()

    return {
        "total_cost_usd": round(float(total.cost), 4),
        "total_tokens_in": int(total.tokens_in),
        "total_tokens_out": int(total.tokens_out),
        "total_calls": int(total.calls),
        "by_operation": [
            {
                "operation": row.operation,
                "calls": row.calls,
                "tokens_in": int(row.tokens_in or 0),
                "tokens_out": int(row.tokens_out or 0),
                "cost_usd": round(float(row.cost or 0), 4),
            }
            for row in ops
        ],
    }


@router.get("/history")
async def get_usage_history(dl=Depends(get_data_layer)):
    """Daily token usage totals for the last 30 days."""
    session = dl.session
    org_id = dl.org_id
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)

    q = (
        select(
            func.date(TokenUsage.created_at).label("day"),
            func.count(TokenUsage.id).label("calls"),
            func.sum(TokenUsage.tokens_in).label("tokens_in"),
            func.sum(TokenUsage.tokens_out).label("tokens_out"),
            func.sum(TokenUsage.cost_usd).label("cost"),
        )
        .where(TokenUsage.org_id == org_id, TokenUsage.created_at >= cutoff)
        .group_by(func.date(TokenUsage.created_at))
        .order_by(func.date(TokenUsage.created_at))
    )
    rows = (await session.execute(q)).all()

    return {
        "days": [
            {
                "date": str(row.day),
                "calls": row.calls,
                "tokens_in": int(row.tokens_in or 0),
                "tokens_out": int(row.tokens_out or 0),
                "cost_usd": round(float(row.cost or 0), 4),
            }
            for row in rows
        ]
    }
