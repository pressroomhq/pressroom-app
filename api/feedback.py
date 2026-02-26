"""User feedback API."""

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_authenticated_data_layer
from database import get_db
from models import Feedback
from api.user_auth import resolve_supabase_user
from services.data_layer import DataLayer

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackIn(BaseModel):
    category: str
    message: str
    page: str = ""


@router.post("")
async def submit_feedback(
    body: FeedbackIn,
    x_org_id: int | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    profile=Depends(resolve_supabase_user),
):
    """Submit user feedback. Works for authenticated users."""
    fb = Feedback(
        user_id=profile.id if profile else None,
        email=profile.email if profile else "anonymous",
        category=body.category,
        message=body.message,
        page=body.page,
        org_id=x_org_id,
    )
    db.add(fb)
    await db.commit()
    return {"ok": True, "message": "Feedback received — thank you!"}


@router.patch("/{feedback_id}/status")
async def update_feedback_status(
    feedback_id: int,
    db: AsyncSession = Depends(get_db),
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """Toggle feedback status between 'new' and 'resolved' (admin use)."""
    result = await db.execute(select(Feedback).where(Feedback.id == feedback_id))
    fb = result.scalar_one_or_none()
    if not fb:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    fb.status = "resolved" if fb.status == "new" else "new"
    await db.commit()
    return {"ok": True, "status": fb.status}


@router.get("")
async def list_feedback(
    db: AsyncSession = Depends(get_db),
    dl: DataLayer = Depends(get_authenticated_data_layer),
):
    """List all feedback (admin use)."""
    result = await db.execute(
        select(Feedback).order_by(Feedback.created_at.desc()).limit(100)
    )
    items = result.scalars().all()
    return [
        {
            "id": f.id,
            "email": f.email,
            "category": f.category,
            "message": f.message,
            "page": f.page,
            "status": f.status,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in items
    ]
