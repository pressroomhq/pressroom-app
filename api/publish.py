"""Publish endpoints — push approved content to destinations via DF social services."""

from fastapi import APIRouter, Depends

from api.auth import get_authenticated_data_layer
from services.data_layer import DataLayer
from services.publisher import publish_approved

router = APIRouter(prefix="/api/publish", tags=["publish"])


@router.post("")
async def trigger_publish(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Publish all approved content according to per-channel action settings."""
    results = await publish_approved(dl)

    def _status(r):
        return r.get("result", {}).get("status", "")

    return {
        "published": len([r for r in results if "error" not in r and _status(r) != "disabled"]),
        "errors": len([r for r in results if "error" in r]),
        "disabled": len([r for r in results if _status(r) == "disabled"]),
        "sent_to_slack": len([r for r in results if _status(r) == "sent_to_slack"]),
        "results": results,
    }
