"""Activity Log endpoints — persistent war room log."""

import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc

from database import get_data_layer, async_session
from models import ActivityLog
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/log", tags=["log"])


class LogEntry(BaseModel):
    level: str = "info"
    message: str


@router.post("")
async def write_log(entry: LogEntry, dl: DataLayer = Depends(get_data_layer)):
    """Write an activity log entry (org-scoped)."""
    log_item = ActivityLog(
        org_id=dl.org_id,
        level=entry.level,
        message=entry.message,
        timestamp=datetime.datetime.utcnow(),
    )
    dl.session.add(log_item)
    await dl.commit()
    return {
        "id": log_item.id,
        "level": log_item.level,
        "message": log_item.message,
        "timestamp": log_item.timestamp.isoformat() if log_item.timestamp else None,
    }


@router.get("")
async def read_log(limit: int = 100, dl: DataLayer = Depends(get_data_layer)):
    """Return last N log entries for the current org, newest first."""
    query = select(ActivityLog).order_by(desc(ActivityLog.timestamp)).limit(limit)
    if dl.org_id:
        query = query.where(ActivityLog.org_id == dl.org_id)
    result = await dl.session.execute(query)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "level": r.level,
            "message": r.message,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in reversed(rows)  # return oldest first for display
    ]
